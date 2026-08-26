package ai

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type AIChatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type AIRequest struct {
	Model    string          `json:"model"`
	Messages []AIChatMessage `json:"messages"`
}

type AIResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
}

func CallOmniRoute(prompt string) (string, error) {
	url := "http://127.0.0.1:20128/v1/chat/completions"
	
	reqBody := AIRequest{
		Model: "gemini-3.5-flash-low",
		Messages: []AIChatMessage{
			{Role: "user", Content: prompt},
		},
	}
	jsonBody, _ := json.Marshal(reqBody)

	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(jsonBody))
	req.Header.Set("Authorization", "Bearer sk-0000000000000000-d01a0e-cf23168c") // OmniRoute Standard Local Key
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("OmniRoute failed: %s", string(body))
	}

	var aiResp AIResponse
	json.NewDecoder(resp.Body).Decode(&aiResp)
	
	if len(aiResp.Choices) > 0 {
		return aiResp.Choices[0].Message.Content, nil
	}
	return "", fmt.Errorf("No response from AI")
}

func GenerateEmailDraft(businessName, category, demoURL string) (string, error) {
	offer := ""
	if demoURL != "" {
		offer = "I already built a fully customized live website for " + businessName + ". You can see it live here: " + demoURL
	} else {
		offer = "I noticed your website has some gaps. I can build a custom demo for you to review."
	}

	prompt := fmt.Sprintf(`
Write a very short highly customized cold email to %s, a %s business.
%s
CRITICAL RULES:
1. Keep the body under 50 words.
2. Provide the Subject Line on the first line.
3. Be professional and brief. Do not introduce who you are.`, businessName, category, offer)

	return CallOmniRoute(prompt)
}
