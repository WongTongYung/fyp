import threading
import queue

def main():
    t1 = threading.Thread(target=capture_thread, args=(cap, save_queue, process_queue, stop_event))

if __name__ == "__main__":
    main()