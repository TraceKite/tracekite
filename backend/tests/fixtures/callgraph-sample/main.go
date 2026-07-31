package main

import "net/http"

func main() {
	http.HandleFunc("/api/users/{id}", getUser)
}

func getUser(w http.ResponseWriter, r *http.Request) {
	fetchUser()
	w.Write([]byte("ok"))
}

func fetchUser() {}
