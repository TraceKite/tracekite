package internal

import "net/http"

// Serves the endpoint orders-service calls. Neither file names the other.
func Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /v1/invoices/{id}", handleInvoices)
}

func handleInvoices(w http.ResponseWriter, r *http.Request) {}
