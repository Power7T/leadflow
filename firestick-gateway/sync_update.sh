#!/bin/bash
adb connect 192.168.8.246:5555
sleep 1
adb -s 192.168.8.246:5555 push ~/leadflow-gateway/leadflow-gateway-armv7 /data/local/tmp/leadflow-gateway
