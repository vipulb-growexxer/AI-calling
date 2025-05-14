"""
Utility functions for analyzing text content from user responses.
"""

def detect_callback_request(text):
    """
    Detects if the user is requesting to be called back later.
    
    Args:
        text (str): The user's response text
        
    Returns:
        bool: True if a callback request is detected, False otherwise
    """
    if not text:
        return False
        
    # Convert to lowercase for case-insensitive matching
    text = text.lower()
    
    # Key phrases indicating the user wants to be called back later
    callback_phrases = [
        "call back",
        "call me back",
        "call later",
        "busy now",
        "busy right now",
        "i'm busy",
        "i am busy",
        "busy please",
        "please busy", 
        "can't talk",
        "cannot talk",
        "not available",
        "in a meeting",
        "driving now",
        "driving right now",
        "call some other time",
        "another time",
        "not a good time",
        "bad time",
        "inconvenient",
        "call tomorrow",
        "call me tomorrow",
        "reach out later",
        "contact later"
    ]
    
    # Key phrases that must appear with time indicators
    time_dependent_phrases = [
        "busy",
        "occupied",
        "engaged",
        "unavailable"
    ]
    
    time_indicators = [
        "now",
        "right now",
        "at the moment",
        "currently",
        "today",
        "later",
        "after",
        "tomorrow"
    ]
    
    # Check for direct callback phrases
    for phrase in callback_phrases:
        if phrase in text:
            return True
            
    # Check for time-dependent phrases with time indicators
    for phrase in time_dependent_phrases:
        if phrase in text:
            for indicator in time_indicators:
                if indicator in text:
                    return True
    
    return False
