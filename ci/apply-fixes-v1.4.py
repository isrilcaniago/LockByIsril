from pathlib import Path

root = Path("extracted/LockByIsril")

service = root / "app/src/main/java/com/isril/lockbyisril/LockAccessibilityService.java"
text = service.read_text(encoding="utf-8")

# Imports needed to verify the actual active foreground window before showing the lock.
text = text.replace(
    'import android.view.accessibility.AccessibilityEvent;\n',
    'import android.view.accessibility.AccessibilityEvent;\n'
    'import android.view.accessibility.AccessibilityNodeInfo;\n'
    'import android.view.accessibility.AccessibilityWindowInfo;\n'
)

start = text.index('    @Override\n    public void onAccessibilityEvent(AccessibilityEvent event) {')
end = text.index('    private void showLockOverlay(String pkg) {', start)

replacement = r'''    private final Runnable foregroundCheck = this::processForegroundWindow;

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null) return;

        int type = event.getEventType();
        if (type != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
                && type != AccessibilityEvent.TYPE_WINDOWS_CHANGED) {
            return;
        }

        // Samsung can deliver a final stale event from the app that is being closed.
        // Do not trust the event package itself. Wait a few milliseconds, then inspect
        // Android's actual active window and only lock that confirmed foreground app.
        handler.removeCallbacks(foregroundCheck);
        handler.postDelayed(foregroundCheck, 35);
    }

    private void processForegroundWindow() {
        String pkg = getConfirmedForegroundPackage();
        if (pkg == null || pkg.isEmpty()) return;

        // Our own overlay can produce accessibility noise. System UI can briefly become
        // active for notifications and system surfaces, so neither should trigger locking.
        if (pkg.equals(getPackageName()) || "com.android.systemui".equals(pkg)) return;

        if (lastPackage != null && !lastPackage.equals(pkg)) {
            if (Prefs.isAppLocked(this, lastPackage)) {
                SessionManager.markExited(lastPackage);
            }
        }
        lastPackage = pkg;

        if (lockOverlay != null && overlayPackage != null) {
            if (overlayPackage.equals(pkg)) {
                return;
            }

            String oldOverlayPackage = overlayPackage;
            removeLockOverlay();
            SessionManager.markExited(oldOverlayPackage);
        }

        if (!Prefs.isProtectionActive(this)) return;
        if (!Prefs.isAppLocked(this, pkg)) return;
        if (!SessionManager.shouldLock(this, pkg)) return;

        showLockOverlay(pkg);
    }

    private String getConfirmedForegroundPackage() {
        try {
            AccessibilityNodeInfo root = getRootInActiveWindow();
            if (root != null && root.getPackageName() != null) {
                String pkg = root.getPackageName().toString();
                if (!pkg.isEmpty()) return pkg;
            }
        } catch (Exception ignored) {
        }

        try {
            List<AccessibilityWindowInfo> windows = getWindows();
            if (windows != null) {
                for (AccessibilityWindowInfo window : windows) {
                    if (window == null || (!window.isActive() && !window.isFocused())) continue;
                    AccessibilityNodeInfo root = window.getRoot();
                    if (root != null && root.getPackageName() != null) {
                        String pkg = root.getPackageName().toString();
                        if (!pkg.isEmpty()) return pkg;
                    }
                }
            }
        } catch (Exception ignored) {
        }

        return null;
    }

'''

text = text[:start] + replacement + text[end:]
service.write_text(text, encoding="utf-8")

config = root / "app/src/main/res/xml/accessibility_service_config.xml"
text = config.read_text(encoding="utf-8")
text = text.replace(
    'android:accessibilityEventTypes="typeWindowStateChanged|typeWindowsChanged|typeWindowContentChanged"',
    'android:accessibilityEventTypes="typeWindowStateChanged|typeWindowsChanged"'
)
text = text.replace('android:notificationTimeout="0"', 'android:notificationTimeout="20"')
text = text.replace('android:canRetrieveWindowContent="false"', 'android:canRetrieveWindowContent="true"')
if 'android:accessibilityFlags=' not in text:
    text = text.replace(
        'android:accessibilityFeedbackType="feedbackGeneric"\n',
        'android:accessibilityFeedbackType="feedbackGeneric"\n'
        '    android:accessibilityFlags="flagRetrieveInteractiveWindows"\n'
    )
config.write_text(text, encoding="utf-8")

gradle = root / "app/build.gradle"
text = gradle.read_text(encoding="utf-8")
text = text.replace("versionCode 4", "versionCode 5")
text = text.replace("versionName '1.3'", "versionName '1.4'")
gradle.write_text(text, encoding="utf-8")

print("Lock by Isril v1.4 foreground verification fix applied")
