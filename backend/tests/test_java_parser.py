import pytest
from evigraph.parsers.java_parser import JavaParser


class TestJavaParser:
    def test_extract_package(self):
        parser = JavaParser()
        code = "package com.example.service;\npublic class UserService {}"
        pkg = parser._extract_package(code)
        assert pkg == "com.example.service"
    
    def test_extract_imports(self):
        parser = JavaParser()
        code = """
import org.springframework.web.bind.annotation.RestController;
import java.util.List;
import static org.junit.Assert.*;
"""
        imports = parser._extract_imports(code)
        assert len(imports) == 3
        assert imports[0].module == "org.springframework.web.bind.annotation.RestController"
        assert imports[1].module == "java.util.List"
        assert imports[2].is_wildcard  # static import with *
    
    def test_extract_classes(self):
        parser = JavaParser()
        code = """
@RestController
public class UserController {
    public List<User> getUsers() {
        return new ArrayList<>();
    }
}
"""
        result = parser.parse("UserController.java", code)
        assert len(result.entities) > 0

        classes = [e for e in result.entities if e.type == "class"]
        assert len(classes) == 1
        assert classes[0].name == "UserController"
    
    def test_spring_endpoints(self):
        parser = JavaParser()
        code = """
@RestController
@RequestMapping("/api/users")
public class UserController {
    @GetMapping
    public List<User> getUsers() { return null; }
    
    @PostMapping("/{id}")
    public User createUser(@PathVariable Long id) { return null; }
}
"""
        result = parser.parse("UserController.java", code)

        assert len(result.api_endpoints) >= 2

        get_ep = [ep for ep in result.api_endpoints if ep.method == "GET"]
        assert len(get_ep) > 0
    
    def test_interface_detection(self):
        parser = JavaParser()
        code = "public interface UserRepository { List<User> findAll(); }"
        result = parser.parse("UserRepository.java", code)
        
        interfaces = [e for e in result.entities if e.type == "interface"]
        assert len(interfaces) == 1
        assert interfaces[0].name == "UserRepository"


class TestPythonParser:
    def test_extract_functions(self):
        from evigraph.parsers.python_parser import PythonParser
        parser = PythonParser()
        code = """
def hello_world():
    print("Hello")

def process_data(items: list) -> dict:
    return {}
"""
        result = parser.parse("test.py", code)
        
        functions = [e for e in result.entities if e.type == "function"]
        assert len(functions) == 2
        assert functions[0].name == "hello_world"
        assert functions[1].name == "process_data"
    
    def test_extract_classes(self):
        from evigraph.parsers.python_parser import PythonParser
        parser = PythonParser()
        code = """
class UserService:
    def __init__(self):
        self.users = []
    
    def get_user(self, id: int) -> User:
        return self.users[id]
"""
        result = parser.parse("test.py", code)
        
        classes = [e for e in result.entities if e.type == "class"]
        assert len(classes) == 1
        assert classes[0].name == "UserService"

        methods = [e for e in result.entities if e.type == "method"]
        assert len(methods) == 2  # __init__ and get_user
    
    def test_fastapi_routes(self):
        from evigraph.parsers.python_parser import PythonParser
        parser = PythonParser()
        code = """
from fastapi import FastAPI
app = FastAPI()

@app.get("/users")
def list_users():
    return []

@app.post("/users")
def create_user(user: User):
    return user
"""
        result = parser.parse("main.py", code)
        
        assert len(result.api_endpoints) == 2
        get_ep = [ep for ep in result.api_endpoints if ep.method == "GET"]
        assert len(get_ep) == 1
        assert get_ep[0].path == "/users"
    
    def test_extract_imports(self):
        from evigraph.parsers.python_parser import PythonParser
        parser = PythonParser()
        code = """
import os
import sys
from typing import List, Dict
from fastapi import FastAPI, Request
"""
        result = parser.parse("test.py", code)
        
        assert len(result.imports) >= 4
        modules = [imp.module for imp in result.imports]
        assert "os" in modules
        assert "typing" in modules
        assert "fastapi" in modules
