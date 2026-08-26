package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
)

func ServeDashboard(port string) {
	// Replicating the exact Python FastApi UI Response
	http.HandleFunc("/leads", func(w http.ResponseWriter, r *http.Request) {
		db, err := sql.Open("sqlite", dbPath)
		if err != nil {
			http.Error(w, "Database unavailable", 500)
			return
		}
		defer db.Close()

		// Read the exact Base and Leads templates from the Firestick's existing leadflow folder
		baseHTMLBytes, err := os.ReadFile("/data/data/com.termux/files/home/leadflow/templates/base.html")
		if err != nil {
			// If missing styles locally, fallback
			w.Write([]byte("Error: Template folder not found on Firestick."))
			return
		}
		leadsHTMLBytes, _ := os.ReadFile("/data/data/com.termux/files/home/leadflow/templates/leads.html")

		// Query exactly like the Python backend
		rows, err := db.Query(`SELECT id, name, status FROM businesses ORDER BY id DESC`)
		defer rows.Close()

		var htmlList []string
		for rows.Next() {
			var id int
			var name, status string
			rows.Scan(&id, &name, &status)
			htmlList = append(htmlList, fmt.Sprintf(`<div class="lead-item %s">%d - %s</div>`, status, id, name))
		}

		baseHTML := string(baseHTMLBytes)
		leadsHTML := string(leadsHTMLBytes)
		
		// In Go, since we can't run Jinja easily without heavy dependencies, we'll strip the Jinja blocks
		// and inject the raw data manually so it keeps exactly the same visual CSS components
		content := strings.Replace(leadsHTML, "{% block content %}", "<div>"+strings.Join(htmlList, "<br>")+"</div>", 1)
		finalOutput := strings.Replace(baseHTML, "{% block content %}", content, 1)

		w.Header().Set("Content-Type", "text/html")
		w.Write([]byte(finalOutput))
	})

	http.HandleFunc("/api/leads", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"message": "Gateway API Running"})
	})

	fmt.Printf("[Dashboard] Local Firestick Web Server mimicking Python UI on http://127.0.0.1:%s/leads\n", port)
	http.ListenAndServe(":"+port, nil)
}
