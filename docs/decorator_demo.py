# Demonstration: Python decorators
# Run this file: python docs/decorator_demo.py

# -------------------------------------------------------------------
# A decorator is just a function that WRAPS another function.
# The @ symbol is shorthand for: func = decorator(func)
# -------------------------------------------------------------------


# -------------------------------------------------------------------
# PART 1: What a decorator actually is
# -------------------------------------------------------------------

def my_decorator(func):
    def wrapper():
        print("-- before the function runs --")
        func()                              # call the original function
        print("-- after the function runs --")
    return wrapper                          # return the wrapped version


def say_hello():
    print("Hello!")

# Without @ syntax — manual wrapping:
say_hello = my_decorator(say_hello)         # this is exactly what @ does
say_hello()
print()

# With @ syntax — same thing, cleaner:
@my_decorator
def say_goodbye():
    print("Goodbye!")

say_goodbye()
print()


# -------------------------------------------------------------------
# PART 2: Decorator that passes arguments through
# -------------------------------------------------------------------

def my_decorator_with_args(func):
    def wrapper(*args, **kwargs):           # accept any arguments
        print("-- before --")
        result = func(*args, **kwargs)      # pass them to the original function
        print("-- after --")
        return result
    return wrapper


@my_decorator_with_args
def add(a, b):
    print(f"  adding {a} + {b} = {a + b}")
    return a + b

add(3, 5)
print()


# -------------------------------------------------------------------
# PART 3: How this maps to Flask's @app.route
# -------------------------------------------------------------------
#
# Flask's app.route is a decorator factory — it takes a URL string
# and returns a decorator. That decorator registers the function
# as the handler for that URL.
#
# What Flask does internally (simplified):
#
#   class Flask:
#       def route(self, url):
#           def decorator(func):
#               self.url_map[url] = func    # register: /js/ → js()
#               return func                 # return the function unchanged
#           return decorator
#
# So when you write:
#
#   @app.route('/js/<path:filename>')
#   def js(filename):
#       return send_from_directory(...)
#
# Python executes this as:
#
#   js = app.route('/js/<path:filename>')(js)
#
# Which means:
#   1. app.route('/js/...') is called → returns a decorator
#   2. That decorator is called with the js function
#   3. Flask stores the mapping: URL "/js/..." → js()
#   4. The js function itself is returned unchanged
#
# When a browser requests GET /js/main.js:
#   Flask looks up its url_map → finds js() → calls js("main.js")
# -------------------------------------------------------------------

# Minimal simulation of what Flask's @app.route does:
url_map = {}

def route(url):
    """Decorator factory: takes a URL, returns a decorator."""
    def decorator(func):
        url_map[url] = func             # register the function for this URL
        return func                     # return the function unchanged
    return decorator


@route('/js/<filename>')
def js(filename):
    return f"Serving file: {filename}"

@route('/css/<filename>')
def css(filename):
    return f"Serving CSS: {filename}"


# Simulate a browser request:
def handle_request(url, param):
    handler = url_map.get(url)
    if handler:
        print(handler(param))
    else:
        print("404 Not Found")

handle_request('/js/<filename>', 'main.js')
handle_request('/css/<filename>', 'style.css')
handle_request('/unknown', '')
