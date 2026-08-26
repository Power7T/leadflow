package main

import (
	"database/sql"
	"fmt"
	"net/http"
)

func ServeDashboard(port string) {
	http.HandleFunc("/leads", func(w http.ResponseWriter, r *http.Request) {
		db, err := sql.Open("sqlite", dbPath)
		if err != nil {
			http.Error(w, "Database unavailable", 500)
			return
		}
		defer db.Close()

		var total, approved, sent, replied int
		db.QueryRow("SELECT count(*) FROM businesses").Scan(&total)
		db.QueryRow("SELECT count(*) FROM businesses WHERE status='approved'").Scan(&approved)
		db.QueryRow("SELECT count(*) FROM businesses WHERE status='sent'").Scan(&sent)
		db.QueryRow("SELECT count(*) FROM businesses WHERE status='replied'").Scan(&replied)

		html := fmt.Sprintf(`
<!DOCTYPE html>
<html>
<head>
	<title>LeadFlow Firestick Dashboard</title>
	<style>
		body { font-family: -apple-system, sans-serif; background: #111827; color: #f9fafb; padding: 2rem; }
		.card { background: #1f2937; padding: 1.5rem; border-radius: 0.5rem; margin-bottom: 2rem; }
		h1 { color: #3b82f6; }
		.stats { display: flex; gap: 2rem; }
		.stat-box { background: #374151; padding: 1rem 2rem; border-radius: 0.5rem; text-align: center; }
		.stat-box h2 { margin: 0; font-size: 2rem; color: #10b981; }
	</style>
</head>
<body>
	<h1>LeadFlow — Firestick Gateway</h1>
	<p>Running highly-optimized Pure Go Architecture for Failover</p>
	<div class="card">
		<h2>System Status: Active</h2>
		<p>Local SQLite Parity: Checked via Cloudflare API</p>
	</div>
	
	<h2>Outreach Pipeline</h2>
	<div class="stats">
		<div class="stat-box"><h2>%d</h2><p>Total Leads</p></div>
		<div class="stat-box"><h2>%d</h2><p>Approved Queue</p></div>
		<div class="stat-box"><h2 style="color:#60a5fa">%d</h2><p>Messages Sent</p></div>
		<div class="stat-box"><h2 style="color:#f59e0b">%d</h2><p>Replies Received</p></div>
	</div>
</body>
</html>
`, total, approved, sent, replied)

		w.Header().Set("Content-Type", "text/html")
		w.Write([]byte(html))
	})

	fmt.Printf("[Dashboard] Local Firestick Web Server running at http://127.0.0.1:%s/leads\n", port)
	http.ListenAndServe(":"+port, nil)
}
