class NotFound(Exception):
    """Raised when a resource is not found."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        
    def __str__(self):
        return self.message