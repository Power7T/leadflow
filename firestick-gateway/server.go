package main

import (
	"fmt"
	"net/http"
)

func ServeFullSystem(port string) {
	http.HandleFunc("/send", func(w http.ResponseWriter, r *http.Request) {
		SendEmail("target@lead.com", "Hello", "Here is your demo")
		w.Write([]byte("Email sent via Native Go SMTP"))
	})
	
	http.ListenAndServe(":"+port, nil)
}
