package main

import (
	"fmt"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os/exec"
	"strings"
	"time"
)

func IsPythonServerRunning() bool {
	out, err := exec.Command("pgrep", "-f", "uvicorn server:app").CombinedOutput()
	if err != nil {
		return false
	}
	return len(strings.TrimSpace(string(out))) > 0
}

func ServeDashboard(port string) {
	// If the Python server isn't running on the Firestick, boot it up!
	if !IsPythonServerRunning() {
		fmt.Println("[Dashboard] Booting up native Python FastAPI Server for 100% functionality...")
		cmd := exec.Command("nohup", "python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8766")
		cmd.Dir = "/data/data/com.termux/files/home/leadflow"
		cmd.Start()
		time.Sleep(3 * time.Second) // Give it time to boot
	}

	// Create a reverse proxy to route traffic from the Go port (8765) directly to the Python logic
	target, _ := url.Parse("http://127.0.0.1:8766")
	proxy := httputil.NewSingleHostReverseProxy(target)

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		proxy.ServeHTTP(w, r)
	})

	fmt.Printf("[Dashboard] Go Gateway routing interface seamlessly to native Python UI at http://127.0.0.1:%s\n", port)
	http.ListenAndServe(":"+port, nil)
}
