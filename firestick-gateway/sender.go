package main

import (
	"fmt"
	"net/smtp"
	"os"
)

func SendEmail(to, subject, body string) error {
	from := os.Getenv("EMAIL_USER")
	pass := os.Getenv("EMAIL_PASS")
	smtpHost := "smtp.gmail.com"
	smtpPort := "587"

	msg := []byte("Subject: " + subject + "\r\n\r\n" + body)
	auth := smtp.PlainAuth("", from, pass, smtpHost)

	return smtp.SendMail(smtpHost+":"+smtpPort, auth, from, []string{to}, msg)
}
