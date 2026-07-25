#!/bin/bash
VIVO_IP="$(cat /Users/chandan/leadflow/.vivo_ip)"

echo "📱 Target: $VIVO_IP"
adb connect $VIVO_IP >/dev/null

echo "📸 Dumping UI to /sdcard/window_dump.xml..."
adb -s $VIVO_IP shell uiautomator dump /sdcard/window_dump.xml

echo "📥 Pulling XML to local..."
adb -s $VIVO_IP pull /sdcard/window_dump.xml test_dump.xml >/dev/null

echo "🔍 Analyzing screen..."
if grep -qi "Try again later" test_dump.xml; then
    echo "🚨 DETECTED: 'Try again later' Action Block!"
elif grep -qi "We restrict certain activity" test_dump.xml; then
    echo "🚨 DETECTED: 'Restrict certain activity' Action Block!"
elif grep -qi "Couldn't refresh feed" test_dump.xml; then
    echo "⚠️ DETECTED: Network/Session error."
else
    echo "✅ Screen looks clear of known blockers."
fi

# Show top app
echo "📱 Current foreground focus:"
adb -s $VIVO_IP shell dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp' | head -2
