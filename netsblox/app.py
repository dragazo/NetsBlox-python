#!/usr/bin/env python

import tkinter as tk
from tkinter import ttk
import multiprocessing as mproc
import subprocess
import threading
import traceback
import turtle
import sys
import io

import netsblox.turtle as nbturtle

root = None
toolbar = None
content = None

_print_queue = mproc.Queue(maxsize = 256)
_print_batchsize = 256
_print_targets = []
def _process_print_queue():
    for _ in range(_print_batchsize):
        if _print_queue.empty():
            break
        val = _print_queue.get()
        for target in _print_targets:
            try:
                target.write(val)
            except:
                pass # throwing would break print queue
    root.after(33, _process_print_queue)

def indent(txt: str):
    return '\n'.join([ f'    {x}' for x in txt.splitlines() ])

def exec_wrapper(*args):
    try:
        exec(*args)
    except:
        print(traceback.format_exc(), file = sys.stderr) # print out directly so that the stdio wrappers are used

_exec_process = None
def play_button():
    global _exec_process

    # if already running, just kill it - the only locks they can have were made by them, so no deadlocking issues.
    # the messaging pipe is broken, but we won't be using it anymore.
    if _exec_process is not None:
        _exec_process.terminate()
        _exec_process = None
        toolbar.run_button.show_play()
        return

    toolbar.run_button.show_stop()

    # wipe whatever was on the display
    content.display.turtle_disp.screen.clear()
    content.display.terminal.text.set_text('')
    nbturtle._new_game()

    # the first turtle on a blank screen for some reason clears click/key events,
    # so make an invisible turtle and then reset the click events
    turtle.RawTurtle(content.display.turtle_disp.canvas, visible = False)
    content.display.turtle_disp.screen.onclick(content.display.turtle_disp.screen.listen)

    def file_piper(src, dst):
        src = io.TextIOWrapper(src)
        for c in iter(lambda: src.read(1), ''):
            dst.write(c)
            dst.flush()

    code = content.project.get_full_script()
    _exec_process = subprocess.Popen([sys.executable, '-uc', code], stdout = subprocess.PIPE, stderr = subprocess.PIPE)
    
    # reading the pipes is blocking so do in another thread for each stream - they will exit when process is killed
    threading.Thread(target = file_piper, args = (_exec_process.stdout, sys.stdout), daemon = True).start()
    threading.Thread(target = file_piper, args = (_exec_process.stderr, sys.stderr), daemon = True).start()

class Toolbar(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.pack(side = tk.TOP, fill = tk.X)

        self.run_button = StartStopButton(self, command = play_button)
        self.run_button.pack()

class StartStopButton(tk.Button):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, width = 5, **kwargs)
        self.show_play()

    def show_play(self):
        self.config(text = '▶', bg = '#2d9e29', fg = 'white')
    def show_stop(self):
        self.config(text = '■', bg = '#b31515', fg = 'white')

class Content(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.pack(side = tk.BOTTOM, fill = tk.BOTH, expand = True)

        self.project = ProjectEditor(self)
        self.display = Display(self)

        self.project.grid(row = 0, column = 0, sticky = tk.NSEW)
        self.display.grid(row = 0, column = 1, sticky = tk.NSEW)

        self.grid_columnconfigure(0, weight = 1, uniform = 'content')
        self.grid_columnconfigure(1, weight = 1, uniform = 'content')
        self.grid_rowconfigure(0, weight = 1)

class ProjectEditor(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.turtle_index = 0
        self.editors = {}

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill = tk.BOTH, expand = True)

        editor = GlobalEditor(self.notebook)
        self.notebook.add(editor, text = 'global')
        self.editors['global'] = editor

        editor = StageEditor(self.notebook, 'stage')
        self.notebook.add(editor, text = editor.name)
        self.editors[editor.name] = editor

        self.newturtle('turtle')

    def newturtle(self, name = None):
        if name is None:
            self.turtle_index += 1
            name = f'turtle{self.turtle_index}'

        if name not in self.editors:
            editor = TurtleEditor(self.notebook, name)
            self.notebook.add(editor, text = name)
            self.editors[name] = editor
    
    def get_full_script(self):
        script = ''
        for editor in self.editors.values():
            partial = editor.get_script()
            script += f'\n{partial}\n'
        script += '\nstart_project()\n'
        return script

# source: https://stackoverflow.com/questions/16369470/tkinter-adding-line-number-to-text-widget
class TextLineNumbers(tk.Canvas):
    def __init__(self, parent, *, target, width):
        super().__init__(parent, width = width)
        self.width = width
        self.textwidget = target

    def redraw(self):
        self.delete('all')

        i = self.textwidget.index('@0,0')
        while True:
            dline = self.textwidget.dlineinfo(i)
            if dline is None:
                break

            y = dline[1]
            linenum = str(i).split('.')[0]
            self.create_text(self.width - 2, y, anchor = 'ne', text = linenum)
            i = self.textwidget.index(f'{i}+1line')

# source: https://stackoverflow.com/questions/16369470/tkinter-adding-line-number-to-text-widget
class ChangedText(tk.Text):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # create a proxy for the underlying widget
        self._orig = self._w + '_orig'
        self.tk.call('rename', self._w, self._orig)
        self.tk.createcommand(self._w, self._proxy)

    def _proxy(self, *args):
        # let the actual widget perform the requested action
        cmd = (self._orig, *args)
        result = self.tk.call(cmd)

        # generate an event if something was added or deleted, or the cursor position changed
        changed = args[0] in ('insert', 'replace', 'delete') or \
            args[0:3] == ('mark', 'set', 'insert') or \
            args[0:2] == ('xview', 'moveto') or \
            args[0:2] == ('xview', 'scroll') or \
            args[0:2] == ('yview', 'moveto') or \
            args[0:2] == ('yview', 'scroll')
        if changed:
            self.event_generate('<<Change>>', when = 'tail')

        return result # return what the actual widget returned

class ScrolledText(tk.Frame):
    def __init__(self, parent, *, readonly = False, linenumbers = False):
        super().__init__(parent)

        self.scrollbar = tk.Scrollbar(self)
        self.text = ChangedText(self, yscrollcommand = self.scrollbar.set)
        self.scrollbar.config(command = self.text.yview)

        def on_select_all(e):
            self.text.tag_add(tk.SEL, '1.0', tk.END)
            return 'break'
        self.text.bind('<Control-Key-a>', on_select_all)
        self.text.bind('<Control-Key-A>', on_select_all)

        if readonly:
            # make text readonly be ignoring all (default) keystrokes
            self.text.bind('<Key>', lambda e: 'break')

            # catching all keys above means we can't copy anymore - impl manually
            def on_copy(e):
                self.clipboard_clear()
                self.clipboard_append(self.text.selection_get())
                return 'break'
            self.text.bind('<Control-Key-c>', on_copy)
            self.text.bind('<Control-Key-C>', on_copy)
        else:
            def on_tab(e):
                self.text.insert(tk.INSERT, '    ')
                return 'break'
            self.text.bind('<Tab>', on_tab)
        
        if linenumbers:
            self.linenumbers = TextLineNumbers(self, target = self.text, width = 30)

            def on_change(e):
                self.linenumbers.redraw()
            self.text.bind('<<Change>>', on_change)
            self.text.bind('<Configure>', on_change)
        
        self.scrollbar.pack(side = tk.RIGHT, fill = tk.Y)
        if linenumbers:
            self.linenumbers.pack(side = tk.LEFT, fill = tk.Y)
        self.text.pack(side = tk.RIGHT, fill = tk.BOTH, expand = True)
    
    def set_text(self, txt):
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', txt)

class CodeEditor(ScrolledText):
    def __init__(self, parent):
        super().__init__(parent, linenumbers = True)

class GlobalEditor(CodeEditor):
    def __init__(self, parent):
        super().__init__(parent)

        self.set_text('''
import netsblox
from netsblox.turtle import *

import time as tryt
import numpy
print(tryt.time())
print(numpy.zeros([2, 4]))

someval = 'hello world' # create a global variable
'''.strip())

    def get_script(self):
        return self.text.get('1.0', 'end-1c')

class StageEditor(CodeEditor):
    def __init__(self, parent, name):
        super().__init__(parent)
        self.name = name

        self.set_text('''
@onstart
def start(self):
    self.myvar = 5                 # create a stage variable
    print('value is:', self.myvar) # access stage variable

    for i in range(10):
        print(i ** 2)
'''.strip())

    def get_script(self):
        raw = self.text.get('1.0', 'end-1c')
        return f'@stage\nclass {self.name}:\n{indent(raw)}\n{self.name} = {self.name}()'

class TurtleEditor(CodeEditor):
    def __init__(self, parent, name):
        super().__init__(parent)
        self.name = name

        self.set_text('''
@onstart
def start(self):
    self.myvar = 40 # create a sprite variable

    for i in range(400):
        self.forward(self.myvar) # access sprite variable
        self.right(90)
'''.strip())

    def get_script(self):
        raw = self.text.get('1.0', 'end-1c')
        return f'@turtle\nclass {self.name}:\n{indent(raw)}\n{self.name} = {self.name}()'

class Display(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.turtle_disp = TurtleDisplay(self)
        self.terminal = TerminalOutput(self)

        self.turtle_disp.grid(row = 0, column = 0, sticky = tk.NSEW)
        self.terminal.grid(row = 1, column = 0, sticky = tk.NSEW)

        self.grid_columnconfigure(0, weight = 1)
        self.grid_rowconfigure(0, weight = 1, uniform = 'display')
        self.grid_rowconfigure(1, weight = 1, uniform = 'display')

class TerminalOutput(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        def style(control):
            control.config(bg = '#1a1a1a', fg = '#bdbdbd', insertbackground = '#bdbdbd')

        self.entry = tk.Entry(self)
        self.entry.pack(side = tk.BOTTOM, fill = tk.X)
        style(self.entry)

        self.text = ScrolledText(self, readonly = True)
        self.text.pack(side = tk.TOP, fill = tk.BOTH, expand = True)
        style(self.text.text)

    def wrap_stdio(self, *, tee: bool):
        _print_targets.append(self)

        class TeeWriter:
            encoding = 'utf-8'

            def __init__(self, old):
                self.old = old

            def write(self, data):
                data = str(data)
                if self.old is not None:
                    self.old.write(data)
                    self.old.flush()
                _print_queue.put(data)
            
            def flush(self):
                pass
            def __len__(self):
                return 0

        sys.stdout = TeeWriter(sys.stdout if tee else None)
        sys.stderr = TeeWriter(sys.stderr if tee else None)
    
    def write(self, txt):
        self.text.text.insert('end', str(txt))
        self.text.text.see(tk.END)
    def write_line(self, txt):
        self.write(f'{txt}\n')

class TurtleDisplay(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.canvas = turtle.ScrolledCanvas(self)
        self.canvas.pack(fill = tk.BOTH, expand = True)

        self.screen = turtle.TurtleScreen(self.canvas)

        # ScrolledCanvas has better behavior, but we dont actually want scrollbars, so always match display size
        self.canvas.bind('<Configure>', lambda e: self.screen.screensize(canvwidth = e.width, canvheight = e.height))

def main():
    global root, toolbar, content

    root = tk.Tk()
    root.geometry('1200x600')
    root.minsize(width = 800, height = 400)
    root.title('NetsBlox - Python')
    ttk.Style().theme_use('clam')

    toolbar = Toolbar(root)
    content = Content(root)

    content.display.terminal.wrap_stdio(tee = True)

    _process_print_queue()
    root.mainloop()

if __name__ == '__main__':
    main()
