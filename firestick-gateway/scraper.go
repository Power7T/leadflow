package main

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"net/http"
	"net/url"
	"os"
)

type Scraper struct {
	SerperAPIKey string
}

func (s *Scraper) FetchLeads(query string) ([]map[string]interface{}, error) {
	baseURL := "https://google.serper.dev/places"
	
	reqBody, _ := json.Marshal(map[string]string{
		"q": query,
	})

	req, _ := http.NewRequest("POST", baseURL, bytes.NewBuffer(reqBody))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-KEY", s.SerperAPIKey)

	client := &http.Client{}
	
	proxyURLStr := os.Getenv("HTTP_PROXY")
	tr := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	if proxyURLStr != "" {
		pURL, _ := url.Parse(proxyURLStr)
		tr.Proxy = http.ProxyURL(pURL)
	}
	client.Transport = tr

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var result map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&result)
	
	return []map[string]interface{}{result}, nil
}
