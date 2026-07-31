use actix_web::{get, web, App, HttpResponse};

#[get("/api/users/{id}")]
async fn get_user(path: web::Path<u64>) -> HttpResponse {
    let msg = build_response();
    HttpResponse::Ok().body(msg)
}

fn build_response() -> &'static str {
    "ok"
}

fn main() {
    App::new().service(get_user);
}
