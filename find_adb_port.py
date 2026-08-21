import socket
import sys

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def find_port():
    local_ip = get_ip()
    targets = ["127.0.0.1", local_ip]
    for ip in targets:
        for port in range(37000, 46000):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.002)
                if s.connect_ex((ip, port)) == 0:
                    # Double check if it's the adb port by checking if we can get a response or if it's open
                    return ip, port
    return None

if __name__ == "__main__":
    res = find_port()
    if res:
        ip, port = res
        print(f"{ip}:{port}")
        sys.exit(0)
    else:
        sys.exit(1)
