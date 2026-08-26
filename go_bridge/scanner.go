package main

import (
	"fmt"
	"net"
	"sync"
	"time"
)

func scanPort(port int, results chan<- int, wg *sync.WaitGroup, sem chan struct{}) {
	defer wg.Done()
	address := fmt.Sprintf("127.0.0.1:%d", port)
	conn, err := net.DialTimeout("tcp", address, 5*time.Millisecond)
	if err == nil {
		conn.Close()
		results <- port
	}
	<-sem
}

func main() {
	results := make(chan int, 100)
	var wg sync.WaitGroup
	workerCount := 100
	sem := make(chan struct{}, workerCount)

	for port := 37000; port <= 46000; port++ {
		wg.Add(1)
		sem <- struct{}{}
		go scanPort(port, results, &wg, sem)
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	if found, ok := <-results; ok {
		fmt.Printf("127.0.0.1:%d\n", found)
	}
}
