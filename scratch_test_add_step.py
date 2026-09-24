import time
from auto_prompt_gui import AutoPromptGUI
import tkinter as tk

root = tk.Tk()
app = AutoPromptGUI(root)

# Try to add a step to the active workflow
wf = app._active_workflow
print("Active workflow:", wf.name)
print("Steps before:", len(wf.steps))
try:
    app._add_step()
    print("Steps after:", len(wf.steps))
    print("Add step succeeded!")
except Exception as e:
    import traceback
    traceback.print_exc()
