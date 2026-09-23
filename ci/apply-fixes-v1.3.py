from pathlib import Path

root = Path("extracted/LockByIsril")

service = root / "app/src/main/java/com/isril/lockbyisril/LockAccessibilityService.java"
service.write_text(r'''package com.isril.lockbyisril;

import android.accessibilityservice.AccessibilityService;
import android.app.KeyguardManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.hardware.biometrics.BiometricPrompt;
import android.net.Uri;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.GridLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.List;
import java.util.concurrent.Executor;

public class LockAccessibilityService extends AccessibilityService {
    private String lastPackage;
    private WindowManager windowManager;
    private View lockOverlay;
    private String overlayPackage;
    private TextView overlayMessage;
    private TextView pinDots;
    private PatternView patternView;
    private final StringBuilder pin = new StringBuilder();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private CancellationSignal biometricCancel;

    private final BroadcastReceiver screenReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (Intent.ACTION_SCREEN_OFF.equals(intent.getAction())) {
                SessionManager.clearAll();
                removeLockOverlay();
            }
        }
    };

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);

        IntentFilter filter = new IntentFilter(Intent.ACTION_SCREEN_OFF);
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            registerReceiver(screenReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(screenReceiver, filter);
        }
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null || event.getPackageName() == null) return;

        String pkg = event.getPackageName().toString();
        if (pkg.isEmpty()) return;

        int type = event.getEventType();
        boolean windowEvent =
                type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
                || type == AccessibilityEvent.TYPE_WINDOWS_CHANGED
                || type == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED;

        if (!windowEvent) return;

        // Ignore our own windows and System UI noise. The overlay itself belongs to this package.
        if (pkg.equals(getPackageName()) || "com.android.systemui".equals(pkg)) return;

        // If the user has moved away from the protected app, remove the overlay immediately.
        if (lockOverlay != null && overlayPackage != null && !overlayPackage.equals(pkg)) {
            String oldOverlayPackage = overlayPackage;
            removeLockOverlay();
            SessionManager.markExited(oldOverlayPackage);
        }

        if (lastPackage != null
                && !lastPackage.equals(pkg)
                && !lastPackage.equals(getPackageName())
                && !"com.android.systemui".equals(lastPackage)
                && Prefs.isAppLocked(this, lastPackage)) {
            SessionManager.markExited(lastPackage);
        }

        lastPackage = pkg;

        if (!Prefs.isProtectionActive(this)) return;
        if (!Prefs.isAppLocked(this, pkg)) return;
        if (!SessionManager.shouldLock(this, pkg)) return;

        if (lockOverlay == null) showLockOverlay(pkg);
    }

    private void showLockOverlay(String pkg) {
        if (windowManager == null || lockOverlay != null) return;

        overlayPackage = pkg;
        pin.setLength(0);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        ImageView bg = new ImageView(this);
        bg.setBackgroundColor(Color.BLACK);
        bg.setScaleType(ImageView.ScaleType.FIT_CENTER);
        String custom = Prefs.getBackgroundUri(this);
        try {
            if (custom != null) bg.setImageURI(Uri.parse(custom));
            else bg.setImageResource(R.drawable.lock_background);
        } catch (Exception e) {
            bg.setImageResource(R.drawable.lock_background);
        }
        root.addView(bg, new FrameLayout.LayoutParams(-1, -1));

        View dim = new View(this);
        int level = Prefs.getBackgroundDim(this);
        int alpha = level == 0 ? 0 : level == 2 ? 115 : 65;
        dim.setBackgroundColor(Color.argb(alpha, 0, 0, 0));
        root.addView(dim, new FrameLayout.LayoutParams(-1, -1));

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setGravity(Gravity.CENTER_HORIZONTAL);
        content.setPadding(dp(22), dp(38), dp(22), dp(28));
        root.addView(content, new FrameLayout.LayoutParams(-1, -1));

        TextView title = text("Lock by Isril", 22, Color.WHITE);
        title.setGravity(Gravity.CENTER);
        content.addView(title, new LinearLayout.LayoutParams(-1, -2));

        overlayMessage = text(
                Prefs.METHOD_PIN.equals(Prefs.getMethod(this)) ? "Enter PIN" : "Draw pattern",
                17,
                Color.LTGRAY
        );
        overlayMessage.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams mp = new LinearLayout.LayoutParams(-1, -2);
        mp.topMargin = dp(12);
        content.addView(overlayMessage, mp);

        View spacer = new View(this);
        content.addView(spacer, new LinearLayout.LayoutParams(1, 0, 1f));

        if (Prefs.METHOD_PIN.equals(Prefs.getMethod(this))) {
            buildPin(content);
        } else {
            buildPattern(content);
        }

        Button bio = new Button(this);
        bio.setText("Use fingerprint");
        bio.setAllCaps(false);
        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(-1, dp(50));
        bp.topMargin = dp(10);
        content.addView(bio, bp);
        bio.setVisibility(Prefs.isBiometricEnabled(this) ? View.VISIBLE : View.GONE);
        bio.setOnClickListener(v -> authenticateFingerprint());

        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                        | WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_SECURE,
                PixelFormat.TRANSLUCENT
        );
        lp.gravity = Gravity.TOP | Gravity.START;

        try {
            windowManager.addView(root, lp);
            lockOverlay = root;

            if (Prefs.isBiometricEnabled(this)) {
                handler.postDelayed(this::authenticateFingerprint, 350);
            }
        } catch (Exception e) {
            lockOverlay = null;
            overlayPackage = null;
        }
    }

    private void buildPattern(LinearLayout content) {
        patternView = new PatternView(this);
        patternView.setShowLines(Prefs.showPatternLines(this));
        patternView.setShowTouches(Prefs.showPatternTouches(this));
        patternView.setHaptic(Prefs.patternHaptic(this));

        LinearLayout.LayoutParams pp = new LinearLayout.LayoutParams(dp(315), dp(315));
        content.addView(patternView, pp);

        patternView.setListener(this::onPattern);
    }

    private void onPattern(List<Integer> pattern) {
        if (CredentialStore.verify(this, PatternView.serialize(pattern))) {
            unlockOverlay();
        } else {
            overlayMessage.setText("Wrong pattern");
            patternView.showError();
        }
    }

    private void buildPin(LinearLayout content) {
        boolean legacyPinMode = !Prefs.isPinSixDigitConfigured(this);

        LinearLayout pinArea = new LinearLayout(this);
        pinArea.setOrientation(LinearLayout.VERTICAL);
        pinArea.setGravity(Gravity.CENTER_HORIZONTAL);

        pinDots = text("", 27, Color.WHITE);
        pinDots.setGravity(Gravity.CENTER);
        pinArea.addView(pinDots, new LinearLayout.LayoutParams(-1, dp(50)));
        updatePinDots(legacyPinMode);

        GridLayout grid = new GridLayout(this);
        grid.setColumnCount(3);
        grid.setRowCount(4);

        String[] labels = legacyPinMode
                ? new String[]{"1","2","3","4","5","6","7","8","9","⌫","0","OK"}
                : new String[]{"1","2","3","4","5","6","7","8","9","","0","⌫"};

        for (String label : labels) {
            if (label.isEmpty()) {
                View empty = new View(this);
                GridLayout.LayoutParams ep = gridParams();
                grid.addView(empty, ep);
                continue;
            }

            Button b = new Button(this);
            b.setText(label);
            b.setTextSize(19);
            b.setAllCaps(false);
            grid.addView(b, gridParams());

            if ("⌫".equals(label)) {
                b.setOnClickListener(v -> {
                    if (pin.length() > 0) pin.deleteCharAt(pin.length() - 1);
                    updatePinDots(legacyPinMode);
                    overlayMessage.setText("Enter PIN");
                });
            } else if ("OK".equals(label)) {
                b.setOnClickListener(v -> submitPin(legacyPinMode));
            } else {
                b.setOnClickListener(v -> {
                    int max = legacyPinMode ? 8 : 6;
                    if (pin.length() >= max) return;
                    pin.append(label);
                    updatePinDots(legacyPinMode);
                    if (!legacyPinMode && pin.length() == 6) {
                        handler.postDelayed(() -> submitPin(false), 70);
                    }
                });
            }
        }

        LinearLayout.LayoutParams gp = new LinearLayout.LayoutParams(-2, -2);
        gp.gravity = Gravity.CENTER_HORIZONTAL;
        pinArea.addView(grid, gp);

        LinearLayout.LayoutParams areaParams = new LinearLayout.LayoutParams(-1, -2);
        areaParams.gravity = Gravity.CENTER_HORIZONTAL;
        content.addView(pinArea, areaParams);
    }

    private GridLayout.LayoutParams gridParams() {
        GridLayout.LayoutParams gp = new GridLayout.LayoutParams();
        gp.width = dp(84);
        gp.height = dp(60);
        gp.setMargins(dp(4), dp(4), dp(4), dp(4));
        return gp;
    }

    private void updatePinDots(boolean legacy) {
        if (pinDots == null) return;

        StringBuilder s = new StringBuilder();
        if (legacy) {
            for (int i = 0; i < pin.length(); i++) {
                if (i > 0) s.append("  ");
                s.append("●");
            }
        } else {
            for (int i = 0; i < 6; i++) {
                if (i > 0) s.append("  ");
                s.append(i < pin.length() ? "●" : "○");
            }
        }
        pinDots.setText(s.toString());
    }

    private void submitPin(boolean legacy) {
        if (!legacy && pin.length() != 6) return;
        if (legacy && (pin.length() < 4 || pin.length() > 8)) return;

        if (CredentialStore.verify(this, pin.toString())) {
            unlockOverlay();
        } else {
            pin.setLength(0);
            updatePinDots(legacy);
            overlayMessage.setText("Wrong PIN");
        }
    }

    private void authenticateFingerprint() {
        if (lockOverlay == null) return;
        if (!Prefs.isBiometricEnabled(this) || android.os.Build.VERSION.SDK_INT < 28) return;

        try {
            KeyguardManager km = getSystemService(KeyguardManager.class);
            if (km == null || !km.isDeviceSecure()) {
                overlayMessage.setText("Set a device screen lock before using fingerprint");
                return;
            }

            if (biometricCancel != null) biometricCancel.cancel();
            biometricCancel = new CancellationSignal();
            Executor executor = getMainExecutor();

            BiometricPrompt prompt = new BiometricPrompt.Builder(this)
                    .setTitle("Unlock Lock by Isril")
                    .setSubtitle("Use your fingerprint")
                    .setNegativeButton("Use app lock", executor, (dialog, which) -> {})
                    .build();

            prompt.authenticate(biometricCancel, executor, new BiometricPrompt.AuthenticationCallback() {
                @Override
                public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) {
                    super.onAuthenticationSucceeded(result);
                    unlockOverlay();
                }

                @Override
                public void onAuthenticationFailed() {
                    super.onAuthenticationFailed();
                    if (overlayMessage != null) overlayMessage.setText("Fingerprint not recognized");
                }
            });
        } catch (Exception e) {
            if (overlayMessage != null) overlayMessage.setText("Fingerprint is not available");
        }
    }

    private void unlockOverlay() {
        String pkg = overlayPackage;
        if (pkg != null) SessionManager.markUnlocked(pkg);
        removeLockOverlay();
    }

    private void removeLockOverlay() {
        handler.removeCallbacksAndMessages(null);

        if (biometricCancel != null) {
            biometricCancel.cancel();
            biometricCancel = null;
        }

        View v = lockOverlay;
        lockOverlay = null;
        overlayPackage = null;
        patternView = null;
        pinDots = null;
        overlayMessage = null;
        pin.setLength(0);

        if (v != null && windowManager != null) {
            try {
                windowManager.removeViewImmediate(v);
            } catch (Exception ignored) {}
        }
    }

    @Override
    public void onInterrupt() {
        removeLockOverlay();
    }

    @Override
    public void onDestroy() {
        removeLockOverlay();
        try { unregisterReceiver(screenReceiver); } catch (Exception ignored) {}
        super.onDestroy();
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        return t;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
''', encoding="utf-8")

# More eager app detection for Samsung. Window content changes give us an event as soon
# as the target app begins drawing, and the accessibility overlay is displayed directly
# by the service instead of relying on a background Activity launch.
config = root / "app/src/main/res/xml/accessibility_service_config.xml"
text = config.read_text(encoding="utf-8")
text = text.replace(
    'android:accessibilityEventTypes="typeWindowStateChanged|typeWindowsChanged"',
    'android:accessibilityEventTypes="typeWindowStateChanged|typeWindowsChanged|typeWindowContentChanged"'
)
text = text.replace('android:notificationTimeout="50"', 'android:notificationTimeout="0"')
config.write_text(text, encoding="utf-8")

# Version 1.3.
gradle = root / "app/build.gradle"
text = gradle.read_text(encoding="utf-8")
text = text.replace("versionCode 3", "versionCode 4")
text = text.replace("versionName '1.2'", "versionName '1.3'")
gradle.write_text(text, encoding="utf-8")

print("Lock by Isril v1.3 immediate overlay lock applied")
