import tkinter as tk
from auto_prompt_gui import AutoPromptGUI, Workflow

root = tk.Tk()
app = AutoPromptGUI(root)

# Simulate user selecting BambooRiti with 0 steps
wf = Workflow(name="BambooRiti")
app._all_workflows["BambooRiti"] = wf
app._active_workflow = wf
app._populate_workflow_list()

# Click + Add Step
print("Steps before:", len(wf.steps))
try:
    app._add_step()
    print("Steps after:", len(wf.steps))
    # Check if a card was actually created
    cards = app._step_frames
    print("Cards created:", len(cards))
except Exception as e:
    import traceback
    traceback.print_exc()

# Let's force an update to see if Tkinter crashes during drawing
try:
    root.update()
    print("Tkinter update successful!")
except Exception as e:
    print("Tkinter crash!")
    import traceback
    traceback.print_exc()
