package main

import (
	"fmt"
	"os"
	"github.com/Power7T/leadflow-gateway/ai"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: leadflow-gateway <niche> | watchdog | autopilot | write 'Business Name'")
		return
	}
	
	go ServeDashboard("8765")
	
	command := os.Args[1]

	if command == "watchdog" {
		fmt.Println("Starting LeadFlow Gateway Failover Watchdog...")
		CheckFailover()
		return
	}
	
	if command == "write" {
		if len(os.Args) < 3 {
			fmt.Println("Provide business name")
			return
		}
		biz := os.Args[2]
		draft, err := ai.GenerateEmailDraft(biz, "Local Business", "")
		if err != nil {
			fmt.Println("AI Error:", err)
		} else {
			fmt.Println("--- GENUINE AI DRAFT ---")
			fmt.Println(draft)
		}
		return
	}

	if command == "autopilot" {
		fmt.Println("Gateway running in Autopilot fallback mode.")
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
		fmt.Printf("Success! Scraped leads via Serper.dev.\nPreview: %+v\n", result)
	}
}
