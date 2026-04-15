# Demonstration: Python global variables
# Run this file: python docs/global_demo.py

# -------------------------------------------------------------------
# Module-level variable (defined at the top of the file)
# Every function in this file can READ it freely.
# But to WRITE to it inside a function, you need the `global` keyword.
# -------------------------------------------------------------------

_connection = None   # starts as None, like _cmd_queue in server.py


# -------------------------------------------------------------------
# WITHOUT global — writing creates a local variable instead
# -------------------------------------------------------------------

def setup_without_global():
    _connection = "I am local"       # this creates a NEW local variable
    print("inside setup_without_global:", _connection)

setup_without_global()
print("after setup_without_global:", _connection)   # still None — untouched
print()


# -------------------------------------------------------------------
# WITH global — writing updates the module-level variable
# -------------------------------------------------------------------

def setup_with_global():
    global _connection
    _connection = "I am the real connection"   # updates the module-level one

setup_with_global()
print("after setup_with_global:", _connection)   # now updated
print()


# -------------------------------------------------------------------
# Other functions can now read _connection without needing `global`
# (you only need `global` when you WRITE, not when you READ)
# -------------------------------------------------------------------

def use_connection():
    print("use_connection sees:", _connection)   # no `global` needed to read

def another_function():
    print("another_function sees:", _connection) # same — any function can read it

use_connection()
another_function()
print()


# -------------------------------------------------------------------
# How this maps to server.py
# -------------------------------------------------------------------
#
# server.py top of file:
#   _cmd_queue   = None   ← module-level, starts as None
#   _state_queue = None
#   _shm_name    = None
#   _shm_lock    = None
#
# init_display_process() runs once at startup:
#   global _cmd_queue, _state_queue, _shm_name, _shm_lock
#   _cmd_queue   = cmd_queue     ← writes the real Queue into the module variable
#   _state_queue = state_queue
#   _shm_name    = shm_name
#   _shm_lock    = shm_lock
#
# After that, every Flask route in server.py can do:
#   def video_feed():
#       ... use _shm_name ...    ← no `global` needed, just reading
#
#   def post_command():
#       ... _cmd_queue.put(...) ← no `global` needed, just reading + calling a method
#
# -------------------------------------------------------------------
