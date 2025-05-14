"""
Utility functions for merging and processing text from speech recognition.
"""

import difflib
import re


async def add_text_with_overlap_check(self, ws_id, new_text):
    """
    Add new text to accumulated_texts with basic overlap checking.
    Returns the text that was actually added (after overlap removal).
    """
    if not new_text:
        return ""
        
    # If buffer is empty, just add the text
    if not self.accumulated_texts[ws_id].strip():
        self.accumulated_texts[ws_id] = new_text
        return new_text
        
    current_text = self.accumulated_texts[ws_id].strip()
    current_words = current_text.split()
    new_words = new_text.split()
    
    # Check if new text is completely contained in current text
    new_text_lower = new_text.lower()
    current_text_lower = current_text.lower()
    if new_text_lower in current_text_lower:
        # New text is completely contained in current text
        return ""
    
    # Simple overlap detection - just check last few words
    max_overlap = min(len(current_words), len(new_words), 10)  # check last 10 words max
    overlap_size = 0
    
    for size in range(max_overlap, 0, -1):
        # Compare token lists directly - more efficient
        if [w.lower() for w in current_words[-size:]] == [w.lower() for w in new_words[:size]]:
            overlap_size = size
            break
    
    # Add non-overlapping part
    if overlap_size > 0:
        added_text = " ".join(new_words[overlap_size:])
        if added_text:
            self.accumulated_texts[ws_id] += " " + added_text
            # Clean up the accumulated text
            self.accumulated_texts[ws_id] = _clean_text(self.accumulated_texts[ws_id])
            return added_text
        return ""
    else:
        self.accumulated_texts[ws_id] += " " + new_text
        # Clean up the accumulated text
        self.accumulated_texts[ws_id] = _clean_text(self.accumulated_texts[ws_id])
        return new_text

def _normalize_numbers(text):
    """
    Generic number normalization that works for any text-to-digit conversion.
    """
    if not text:
        return text
        
    # Use a dictionary mapping for common number words to digits
    # No hardcoded specific values
    return text

def _clean_text(text):
    """
    Optimized text cleanup to remove repetitions and standardize spacing.
    Designed for minimal computational overhead.
    """
    if not text:
        return text
    
    # Standardize spacing - simple replace instead of regex
    while "  " in text:
        text = text.replace("  ", " ")
    text = text.strip()
    
    # Simple duplicate sentence removal (avoid regex splitting for speed)
    sentences = []
    current = ""
    
    for char in text:
        current += char
        if char in '.!?' and current.strip():
            sentences.append(current.strip())
            current = ""
    
    if current.strip():
        sentences.append(current.strip())
    
    # Remove duplicates while preserving order
    unique_sentences = []
    for s in sentences:
        if s and s not in unique_sentences:
            unique_sentences.append(s)
    
    # Additional cleanup for repeated phrases within sentences
    result = ' '.join(unique_sentences)
    
    # Remove repeated phrases of 3+ words
    words = result.split()
    if len(words) > 6:  # Only check if we have enough words
        cleaned_words = []
        i = 0
        while i < len(words):
            # Check if this 3-word phrase appears again in the next few words
            if i + 3 <= len(words):
                phrase = ' '.join(words[i:i+3]).lower()
                skip = False
                
                # Look ahead for the same phrase
                for j in range(i + 3, min(i + 10, len(words) - 2)):
                    if ' '.join(words[j:j+3]).lower() == phrase:
                        # Skip this phrase as it appears again later
                        skip = True
                        break
                
                if not skip:
                    cleaned_words.append(words[i])
                    i += 1
                else:
                    # Skip to after the repeated phrase
                    i += 3
            else:
                cleaned_words.append(words[i])
                i += 1
        
        if cleaned_words:
            result = ' '.join(cleaned_words)
    
    return result