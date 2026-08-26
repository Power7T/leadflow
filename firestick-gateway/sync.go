package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"

	_ "modernc.org/sqlite" // Pure Go SQLite driver (No CGO)
)

var dbPath = "/data/data/com.termux/files/home/leadflow/leadflow.db"

type SyncTransaction struct {
	Action  string                 `json:"action"`
	Payload map[string]interface{} `json:"payload"`
	LocalID int                    `json:"local_id,omitempty"`
}

func PushLocalChanges() {
	publicURL := os.Getenv("LEADFLOW_PUBLIC_URL")
	token := os.Getenv("SECRET_TOKEN")
	if publicURL == "" || token == "" {
		return
	}

	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		fmt.Printf("[Go Sync] DB Open Error: %v\n", err)
		return
	}
	defer db.Close()

	rows, err := db.Query("SELECT id, action, payload FROM sync_journal WHERE synced=0 ORDER BY id ASC LIMIT 50")
	if err != nil {
		return
	}
	defer rows.Close()

	var transactions []SyncTransaction
	for rows.Next() {
		var id int
		var action, payloadStr string
		if err := rows.Scan(&id, &action, &payloadStr); err == nil {
			var payload map[string]interface{}
			if json.Unmarshal([]byte(payloadStr), &payload) == nil {
				transactions = append(transactions, SyncTransaction{
					Action:  action,
					Payload: payload,
					LocalID: id,
				})
			}
		}
	}

	if len(transactions) == 0 {
		return
	}

	reqBody, _ := json.Marshal(map[string]interface{}{"transactions": transactions})
	req, _ := http.NewRequest("POST", publicURL+"/api/sync", bytes.NewBuffer(reqBody))
	req.Header.Set("X-Secret-Token", token)
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil || resp.StatusCode != 200 {
		return
	}
	defer resp.Body.Close()

	tx, _ := db.Begin()
	for _, tr := range transactions {
		tx.Exec("UPDATE sync_journal SET synced=1 WHERE id=?", tr.LocalID)
	}
	tx.Commit()
	fmt.Printf("[Go Sync] Successfully pushed %d changes.\n", len(transactions))
}

func PullRemoteChanges() {
	publicURL := os.Getenv("LEADFLOW_PUBLIC_URL")
	token := os.Getenv("SECRET_TOKEN")
	if publicURL == "" || token == "" {
		return
	}

	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return
	}
	defer db.Close()

	var lastSeq int
	db.QueryRow("SELECT val FROM sync_state WHERE key='last_sync_seq'").Scan(&lastSeq)

	url := fmt.Sprintf("%s/api/sync?since=%d&token=%s", publicURL, lastSeq, token)
	resp, err := http.Get(url)
	if err != nil || resp.StatusCode != 200 {
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	var data struct {
		Transactions []struct {
			Sequence int                    `json:"sequence"`
			Action   string                 `json:"action"`
			Payload  map[string]interface{} `json:"payload"`
		} `json:"transactions"`
	}
	
	if json.Unmarshal(body, &data) != nil || len(data.Transactions) == 0 {
		return
	}

	tx, _ := db.Begin()
	for _, tr := range data.Transactions {
		// Just mirroring the simple status updates for Go-Scraper capability handling. 
		if tr.Action == "update_business_status" {
            bID := tr.Payload["business_id"]
			tx.Exec("UPDATE businesses SET status=? WHERE id=?", tr.Payload["status"], bID)
		}
		
		if tr.Sequence > lastSeq {
			lastSeq = tr.Sequence
		}
	}
	tx.Exec("INSERT OR REPLACE INTO sync_state (key, val) VALUES ('last_sync_seq', ?)", lastSeq)
	tx.Commit()
	fmt.Printf("[Go Sync] Successfully pulled %d changes.\n", len(data.Transactions))
}
