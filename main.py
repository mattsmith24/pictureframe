import threading
import queue
import pictureframe
import solarweb

terminate_event = threading.Event()
pvdata_queue = queue.SimpleQueue()

t1 = threading.Thread(target=pictureframe.main, args=(terminate_event,pvdata_queue))
t1.start()

t2 = threading.Thread(target=solarweb.main, args=(terminate_event,pvdata_queue))
t2.start()

try:
    while True:
        t1.join(timeout=2.0)
        if not t1.is_alive() or not t2.is_alive():
            terminate_event.set()
            t1.join()
            t2.join()
            break
except KeyboardInterrupt:
    print("CTRL-C received. Killing threads")
    terminate_event.set()
    t1.join()
    t2.join()
