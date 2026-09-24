import time
import logging

# Heavy imports moved to method scope to prevent startup hangs
logger = logging.getLogger(__name__)

class AntigravityVisualDetector:
    """Uses PIL to capture screen and look for Antigravity's Send/Stop buttons to determine state"""
    
    def __init__(self):
        self._last_state = "unknown"
        
    def is_generating(self, hwnd=None) -> bool:
        """
        Takes a screenshot and checks for RED (PIL) OR checks for the 'Stop' button (UIA).
        Returns True if the AI is still working/thinking.
        """
        # --- 1. Fast PIXEL Check (Primary) ---
        try:
            from PIL import ImageGrab
            import ctypes
            user32 = ctypes.windll.user32
            
            # DPI-AWARE CAPTURE: 
            # user32.GetWindowRect returns logical units. 
            # ImageGrab.grab (with bbox) expects physical pixels on Windows.
            try:
                import pyautogui
                physical_w, physical_h = ImageGrab.grab().size
                logical_w, logical_h = pyautogui.size()
                scale = physical_w / logical_w
            except Exception:
                scale = 1.0

            rect = ctypes.wintypes.RECT()
            if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                # Convert logical rect to physical bbox
                bbox = (
                    int(rect.left * scale), 
                    int(rect.top * scale), 
                    int(rect.right * scale), 
                    int(rect.bottom * scale)
                )
                img = ImageGrab.grab(bbox=bbox)
            else:
                img = ImageGrab.grab() # Full screen fallback
                
            pixels = img.load()
            width, height = img.size
            
            red_pixels_found = 0
            blue_pixels_found = 0
            start_y = int(height * 0.7)
            
            for y in range(start_y, height, 5): 
                for x in range(0, width, 5):
                    r, g, b = pixels[x, y]
                    if r > 200 and g < 100 and b < 100:
                        red_pixels_found += 1
                    elif b > 140 and r < b * 0.7 and g < b * 0.9:
                        blue_pixels_found += 1
            
            if red_pixels_found > 10:
                self._last_state = "generating"
                return True
            
            if blue_pixels_found > 10:
                self._last_state = "ready_blue"
                return False
                
        except Exception as e:
            logger.debug(f"PIL check failed: {e}")

        # Default fallbacks
        if self._last_state == "generating":
             # If we were generating but now checks failed, assume we possibly finished
             self._last_state = "ready_empty"
        elif self._last_state != "ready_blue":
             self._last_state = "ready_empty"
             
        return False
