package main

import (
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: leadflow-gateway <niche> | watchdog | autopilot")
		return
	}
	
	command := os.Args[1]

	if command == "watchdog" {
		fmt.Println("Starting LeadFlow Gateway Failover Watchdog...")
		CheckFailover()
		return
	}
	
	if command == "autopilot" {
		fmt.Println("Gateway running in Autopilot fallback mode.")
		// Placeholder for Go loop logic executing scrapes
		return
	}

	niche := command
	scraper := &Scraper{
		SerperAPIKey: os.Getenv("SERPER_API_KEY"),
	}
	result, err := scraper.FetchLeads(niche)
	if err != nil {
		fmt.Printf("Error: %v\n", err)
	} else {
		fmt.Printf("Success! Found Google Maps results via Serper.dev.\nPreview: %+v\n", result)
	}
}
