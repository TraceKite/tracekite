package com.example

import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api/users")
class UserController {
    @GetMapping("/{id}")
    fun getUser(@PathVariable id: Long): String {
        return fetchUser(id)
    }

    private fun fetchUser(id: Long): String {
        return "user"
    }
}
