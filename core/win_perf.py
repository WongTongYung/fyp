"""Windows performance fixes for DroidCam + Intel iGPU.

See PERFORMANCE_NOTES.txt for full explanation.
"""

import atexit
import ctypes
import ctypes.wintypes


def win32_perf_setup():
    """Fix Windows 11 timer resolution + power throttling.

    Requests 1ms timer resolution, disables EcoQoS power throttling,
    and raises process priority so performance is stable regardless
    of which app is in the foreground.
    """
    # 1) Request 1ms timer resolution
    try:
        winmm = ctypes.WinDLL('winmm')
        winmm.timeBeginPeriod(1)
        atexit.register(winmm.timeEndPeriod, 1)
    except Exception:
        pass

    # 2) Disable EcoQoS power throttling for this process
    try:
        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [
                ("Version", ctypes.wintypes.ULONG),
                ("ControlMask", ctypes.wintypes.ULONG),
                ("StateMask", ctypes.wintypes.ULONG),
            ]
        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = 1
        state.ControlMask = 0x1   # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        state.StateMask = 0       # 0 = disable throttling
        ctypes.windll.kernel32.SetProcessInformation(
            ctypes.windll.kernel32.GetCurrentProcess(),
            4,  # ProcessPowerThrottling
            ctypes.byref(state),
            ctypes.sizeof(state),
        )
    except Exception:
        pass

    # 3) Raise process priority to HIGH
    try:
        ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(),
            0x00000080,  # HIGH_PRIORITY_CLASS
        )
    except Exception:
        pass


def keep_igpu_alive():
    """Prevent Intel iGPU from entering low-power state.

    DroidCam's virtual camera uses the Intel iGPU media engine for decoding.
    When no visible window uses the iGPU for rendering, Windows puts it into
    a low-power D-state, causing cap.read() to slow from 60fps to ~17fps.
    This creates a tiny 1x1 hidden window with periodic redraws to keep
    the iGPU active with negligible overhead.

    This function blocks (runs a message pump), so call it from a daemon thread.
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

    # Use proper Win64 types for WPARAM (UINT_PTR) and LPARAM (LONG_PTR)
    LRESULT = ctypes.c_ssize_t
    WPARAM = ctypes.c_size_t
    LPARAM = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM)

    # Set proper arg/res types for DefWindowProcW
    user32.DefWindowProcW.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    def wnd_proc(hwnd, msg, wparam, lparam):
        WM_DESTROY = 0x0002
        WM_TIMER = 0x0113
        if msg == WM_TIMER:
            user32.InvalidateRect(hwnd, None, True)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wnd_proc_cb = WNDPROC(wnd_proc)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.c_uint),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", ctypes.c_void_p),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", ctypes.c_wchar_p),
            ("lpszClassName", ctypes.c_wchar_p),
        ]

    hInstance = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpfnWndProc = wnd_proc_cb
    wc.hInstance = hInstance
    wc.lpszClassName = "iGPU_KeepAlive"
    wc.hbrBackground = gdi32.GetStockObject(0)  # WHITE_BRUSH
    user32.RegisterClassW(ctypes.byref(wc))

    # Create a 1x1 pixel window, off-screen, not visible in taskbar
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    WS_POPUP = 0x80000000
    hwnd = user32.CreateWindowExW(
        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        "iGPU_KeepAlive", "iGPU_KeepAlive",
        WS_POPUP,
        -1, -1, 1, 1,   # off-screen 1x1 pixel
        None, None, hInstance, None
    )
    # Show but keep off-screen (ShowWindow needed for GDI to actually render)
    user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE

    # Set a timer: repaint every 100ms (10fps) -- negligible CPU/GPU cost
    user32.SetTimer(hwnd, 1, 100, None)

    # Run message pump (blocks forever)
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
