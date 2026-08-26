package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"
)

type KVResponse struct {
	Value string `json:"value"`
}

func GetLeaderHeartbeat(url, token string) float64 {
	client := &http.Client{Timeout: 10 * time.Second}
	
	reqBody, _ := json.Marshal(map[string]string{
		"key": "leader:heartbeat",
	})
	
	req, _ := http.NewRequest("POST", url+"/api/kv", bytes.NewBuffer(reqBody))
	req.Header.Set("X-Secret-Token", token)
	req.Header.Set("Content-Type", "application/json")
	
	resp, err := client.Do(req)
	if err != nil {
		fmt.Printf("Health check failed: %v\n", err)
		return 9999.0 
	}
	defer resp.Body.Close()

	if resp.StatusCode == 200 {
		var data KVResponse
		json.NewDecoder(resp.Body).Decode(&data)
		
		if data.Value != "" {
			var vivoHeartbeat float64
			fmt.Sscanf(data.Value, "%f", &vivoHeartbeat)
			ageMs := float64(time.Now().Unix()) - vivoHeartbeat
			return ageMs / 60.0 // Returning minutes
		}
	}
	return 9999.0
}

func IsGatewayActive() bool {
	out, err := exec.Command("pgrep", "-f", "leadflow-gateway autopilot").CombinedOutput()
	if err != nil {
		return false
	}
	return len(strings.TrimSpace(string(out))) > 0
}

func KillGateway() {
	exec.Command("pkill", "-f", "leadflow-gateway autopilot").Run()
	fmt.Println("✅ Vivo is back online. Firestick Gateway yielded primary control.")
}

func RunFailover(topic string) {
	fmt.Println("🚨 Vivo Phone is OFFLINE! Taking over as Primary Gateway on Firestick...")
	
	// Start the Go autopilot mode in the background
	cmd := exec.Command("nohup", "/data/local/tmp/leadflow-gateway", "autopilot")
	cmd.Start()

	// Notify via NTFY
	if topic != "" {
		req, _ := http.NewRequest("POST", "https://ntfy.sh/"+topic, strings.NewReader("⚠️ Vivo phone went offline! Firestick Go Gateway took over 24/7."))
		req.Header.Set("Title", "LeadFlow - Gateway Failover")
		req.Header.Set("Priority", "high")
        http.DefaultClient.Do(req)
	}
}

func WriteFirestickHeartbeat(url, token string) {
	client := &http.Client{Timeout: 5 * time.Second}
	now := fmt.Sprintf("%d", time.Now().Unix())
	
	reqBody, _ := json.Marshal(map[string]string{
		"key": "leader:heartbeat", // Spoof the leader heartbeat so the Mac stays down
		"value": now,
	})
	
	req, _ := http.NewRequest("POST", url+"/api/kv", bytes.NewBuffer(reqBody))
	req.Header.Set("X-Secret-Token", token)
	req.Header.Set("Content-Type", "application/json")
	client.Do(req)
}

func CheckFailover() {
	go SyncDatabaseRoutine()
	publicURL := os.Getenv("LEADFLOW_PUBLIC_URL")
	token := os.Getenv("SECRET_TOKEN")
	ntfyTopic := os.Getenv("NTFY_TOPIC")
	
	if publicURL == "" {
		publicURL = "https://leadflow-relay.chandango12.workers.dev" // fallback
	}

	for {
		age := GetLeaderHeartbeat(publicURL, token)
		fmt.Printf("Vivo last heartbeat age: %.1f minutes\n", age)
		
		isActive := IsGatewayActive()
		
		if age > 10.0 { 
			// Vivo is down (wait 10 min). Firestick takes over before Mac (Mac waits 15+ min)
			if !isActive {
				RunFailover(ntfyTopic)
			} else {
				// While Firestick is active, write its own heartbeat so Mac stays down
				WriteFirestickHeartbeat(publicURL, token)
			}
		} else {
			// Vivo is ALIVE (under 10 mins).
			if isActive {
				// Relinquish control!
				KillGateway()
			}
		}
		
		time.Sleep(3 * time.Minute)
	}
}

func SyncDatabaseRoutine() {
	for {
		// Firestick triggers the existing Python sync engine to maintain DB parity with Vivo/Mac
		// It only needs to sync when it is acting as the Gateway to upload its Scraper progress
		if IsGatewayActive() {
			fmt.Println("[Go Sync] Triggering background Python Database Replication...")
			PushLocalChanges()
			PullRemoteChanges()
		}
		
		// Run every 2 minutes exactly like the Python scheduler
		time.Sleep(2 * time.Minute)
	}
}
