package main

import (
	"net/http"
)

func ScoreWebsite(url string) int {
	resp, err := http.Get(url)
	if err != nil {
		return 0
	}
	defer resp.Body.Close()
	
	score := 50
	if resp.Header.Get("Server") != "" {
		score += 20
	}
	return score
}
