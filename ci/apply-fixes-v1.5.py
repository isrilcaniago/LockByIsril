from pathlib import Path

root = Path("extracted/LockByIsril")

# Remove Accessibility completely from the application package.
access_service = root / "app/src/main/java/com/isril/lockbyisril/LockAccessibilityService.java"
if access_service.exists():
    access_service.unlink()

access_config = root / "app/src/main/res/xml/accessibility_service_config.xml"
if access_config.exists():
    access_config.unlink()

# Manifest for Usage Access + application overlay + foreground monitoring service.
manifest = root / "app/src/main/AndroidManifest.xml"
manifest.write_text(r'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.USE_BIOMETRIC" />
    <uses-permission android:name="android.permission.VIBRATE" />
    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
    <uses-permission android:name="android.permission.PACKAGE_USAGE_STATS" />
    <uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_SPECIAL_USE" />

    <queries>
        <intent>
            <action android:name="android.intent.action.MAIN" />
            <category android:name="android.intent.category.LAUNCHER" />
        </intent>
    </queries>

    <application
        android:allowBackup="false"
        android:fullBackupContent="false"
        android:icon="@drawable/app_icon"
        android:label="@string/app_name"
        android:supportsRtl="true"
        android:theme="@android:style/Theme.Material.NoActionBar">

        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:screenOrientation="portrait">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <activity
            android:name=".AppPickerActivity"
            android:exported="false"
            android:screenOrientation="portrait" />

        <activity
            android:name=".SetupCredentialActivity"
            android:exported="false"
            android:screenOrientation="portrait" />

        <activity
            android:name=".LockActivity"
            android:excludeFromRecents="true"
            android:exported="false"
            android:launchMode="singleTop"
            android:screenOrientation="portrait"
            android:theme="@android:style/Theme.Material.NoActionBar" />

        <service
            android:name=".UsageLockService"
            android:exported="false"
            android:foregroundServiceType="specialUse">
            <property
                android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
                android:value="Locally monitors foreground app changes to lock only apps selected by the device owner." />
        </service>

        <receiver
            android:name=".BootReceiver"
            android:enabled="true"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
            </intent-filter>
        </receiver>
    </application>
</manifest>
''', encoding="utf-8")

# Foreground service based on UsageStatsManager. No Accessibility APIs are used.
service = root / "app/src/main/java/com/isril/lockbyisril/UsageLockService.java"
service.write_text(r'''package com.isril.lockbyisril;

import android.app.AppOpsManager;
import android.app.KeyguardManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.hardware.biometrics.BiometricPrompt;
import android.net.Uri;
import android.os.Build;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.Process;
import android.provider.Settings;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.GridLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.List;
import java.util.concurrent.Executor;

public class UsageLockService extends Service {
    private static final String CHANNEL_ID = "lock_monitor";
    private static final int NOTIFICATION_ID = 1907;
    private static final long POLL_MS = 90L;
    private static final long IDLE_POLL_MS = 500L;

    private static volatile boolean running;

    private UsageStatsManager usageStats;
    private WindowManager windowManager;
    private PowerManager powerManager;
    private final Handler handler = new Handler(Looper.getMainLooper());

    private long lastSeenEventTime;
    private String foregroundPackage;
    private String lastProtectedPackage;

    private View lockOverlay;
    private String overlayPackage;
    private TextView overlayMessage;
    private TextView pinDots;
    private PatternView patternView;
    private final StringBuilder pin = new StringBuilder();
    private CancellationSignal biometricCancel;

    private final Runnable monitor = new Runnable() {
        @Override
        public void run() {
            if (!running) return;

            if (!Prefs.isProtectionEnabled(UsageLockService.this)
                    || !isUsageAccessGranted(UsageLockService.this)
                    || !isOverlayGranted(UsageLockService.this)) {
                removeLockOverlay();
                stopSelf();
                return;
            }

            boolean interactive = powerManager == null || powerManager.isInteractive();
            if (interactive) {
                checkForegroundApp();
                handler.postDelayed(this, POLL_MS);
            } else {
                SessionManager.clearAll();
                removeLockOverlay();
                handler.postDelayed(this, IDLE_POLL_MS);
            }
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        running = true;
        usageStats = (UsageStatsManager) getSystemService(USAGE_STATS_SERVICE);
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        powerManager = (PowerManager) getSystemService(POWER_SERVICE);

        createNotificationChannel();
        startForeground(NOTIFICATION_ID, buildNotification());

        lastSeenEventTime = Math.max(0L, System.currentTimeMillis() - 3000L);
        handler.post(monitor);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (!Prefs.isProtectionEnabled(this)
                || !isUsageAccessGranted(this)
                || !isOverlayGranted(this)) {
            stopSelf();
            return START_NOT_STICKY;
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        handler.removeCallbacksAndMessages(null);
        removeLockOverlay();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void checkForegroundApp() {
        if (usageStats == null) return;

        long now = System.currentTimeMillis();
        long start = Math.max(0L, lastSeenEventTime - 250L);
        UsageEvents events;

        try {
            events = usageStats.queryEvents(start, now);
        } catch (Exception e) {
            return;
        }

        UsageEvents.Event event = new UsageEvents.Event();
        String newestPackage = null;
        long newestTime = lastSeenEventTime;

        while (events != null && events.hasNextEvent()) {
            events.getNextEvent(event);
            int type = event.getEventType();

            boolean resumed = type == UsageEvents.Event.MOVE_TO_FOREGROUND;
            if (Build.VERSION.SDK_INT >= 29) {
                resumed = resumed || type == UsageEvents.Event.ACTIVITY_RESUMED;
            }

            if (resumed && event.getTimeStamp() >= newestTime && event.getPackageName() != null) {
                newestTime = event.getTimeStamp();
                newestPackage = event.getPackageName();
            }
        }

        if (newestPackage == null) return;

        lastSeenEventTime = Math.max(lastSeenEventTime, newestTime);

        if (newestPackage.equals(getPackageName())) {
            foregroundPackage = newestPackage;
            return;
        }

        if (foregroundPackage == null || !foregroundPackage.equals(newestPackage)) {
            onForegroundChanged(newestPackage);
        }
    }

    private void onForegroundChanged(String pkg) {
        String previous = foregroundPackage;
        foregroundPackage = pkg;

        if (previous != null && !previous.equals(pkg) && Prefs.isAppLocked(this, previous)) {
            SessionManager.markExited(previous);
        }

        if (lockOverlay != null && overlayPackage != null && !overlayPackage.equals(pkg)) {
            String old = overlayPackage;
            removeLockOverlay();
            SessionManager.markExited(old);
        }

        if (!Prefs.isProtectionActive(this)) return;
        if (!Prefs.isAppLocked(this, pkg)) {
            lastProtectedPackage = null;
            return;
        }

        lastProtectedPackage = pkg;
        if (!SessionManager.shouldLock(this, pkg)) return;

        showLockOverlay(pkg);
    }

    private void showLockOverlay(String pkg) {
        if (windowManager == null || lockOverlay != null || !Settings.canDrawOverlays(this)) return;

        overlayPackage = pkg;
        pin.setLength(0);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        root.setFocusableInTouchMode(true);
        root.setOnKeyListener((v, keyCode, event) -> {
            if (keyCode == KeyEvent.KEYCODE_BACK && event.getAction() == KeyEvent.ACTION_UP) {
                goHome();
                return true;
            }
            return false;
        });

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

        if (Prefs.METHOD_PIN.equals(Prefs.getMethod(this))) buildPin(content);
        else buildPattern(content);

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
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                        | WindowManager.LayoutParams.FLAG_SECURE,
                PixelFormat.TRANSLUCENT
        );
        lp.gravity = Gravity.TOP | Gravity.START;

        try {
            windowManager.addView(root, lp);
            lockOverlay = root;
            root.requestFocus();

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
                grid.addView(empty, gridParams());
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
        if (!Prefs.isBiometricEnabled(this) || Build.VERSION.SDK_INT < 28) return;

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

    private void goHome() {
        Intent home = new Intent(Intent.ACTION_MAIN);
        home.addCategory(Intent.CATEGORY_HOME);
        home.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(home);
        } catch (Exception ignored) {}
        removeLockOverlay();
    }

    private Notification buildNotification() {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);

        return b.setSmallIcon(R.drawable.app_icon)
                .setContentTitle("Lock by Isril")
                .setContentText("Protection is monitoring selected apps")
                .setOngoing(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;

        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "App protection",
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("Keeps Lock by Isril protection active");
        nm.createNotificationChannel(channel);
    }

    public static boolean isUsageAccessGranted(Context context) {
        try {
            AppOpsManager appOps = (AppOpsManager) context.getSystemService(Context.APP_OPS_SERVICE);
            if (appOps == null) return false;
            int mode = appOps.checkOpNoThrow(
                    AppOpsManager.OPSTR_GET_USAGE_STATS,
                    Process.myUid(),
                    context.getPackageName()
            );
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Exception e) {
            return false;
        }
    }

    public static boolean isOverlayGranted(Context context) {
        return Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(context);
    }

    public static boolean hasRequiredAccess(Context context) {
        return isUsageAccessGranted(context) && isOverlayGranted(context);
    }

    public static void ensureRunning(Context context) {
        if (!Prefs.isProtectionEnabled(context) || !hasRequiredAccess(context)) return;
        Intent i = new Intent(context, UsageLockService.class);
        try {
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(i);
            else context.startService(i);
        } catch (Exception ignored) {}
    }

    public static void stopRunning(Context context) {
        try {
            context.stopService(new Intent(context, UsageLockService.class));
        } catch (Exception ignored) {}
    }

    public static boolean isRunning() {
        return running;
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

# Boot receiver starts the monitor only when both special accesses were already granted.
boot = root / "app/src/main/java/com/isril/lockbyisril/BootReceiver.java"
boot.write_text(r'''package com.isril.lockbyisril;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        SessionManager.clearAll();
        if (Prefs.isProtectionEnabled(context) && UsageLockService.hasRequiredAccess(context)) {
            UsageLockService.ensureRunning(context);
        }
    }
}
''', encoding="utf-8")

# Main settings UI for Usage Access and "Appear on top". No Accessibility option remains.
main = root / "app/src/main/java/com/isril/lockbyisril/MainActivity.java"
main.write_text(r'''package com.isril.lockbyisril;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.KeyguardManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.util.Set;

public class MainActivity extends Activity {
    private static final int REQ_FIRST_SETUP = 10;
    private static final int REQ_UNLOCK_SETTINGS = 11;
    private static final int REQ_CHANGE_CREDENTIAL = 12;
    private static final int REQ_BACKGROUND = 13;

    private boolean verified;
    private TextView statusText;
    private TextView accessText;
    private Switch protectionSwitch;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(18, 18, 18));
        getWindow().setNavigationBarColor(Color.BLACK);

        if (!Prefs.isSetupComplete(this)) {
            Intent i = new Intent(this, SetupCredentialActivity.class);
            i.putExtra(SetupCredentialActivity.EXTRA_METHOD, Prefs.METHOD_PATTERN);
            startActivityForResult(i, REQ_FIRST_SETUP);
        } else {
            requestSettingsUnlock();
        }
    }

    private void requestSettingsUnlock() {
        Intent i = new Intent(this, LockActivity.class);
        i.putExtra(LockActivity.EXTRA_MODE, LockActivity.MODE_SETTINGS);
        i.putExtra(LockActivity.EXTRA_TARGET, getPackageName());
        startActivityForResult(i, REQ_UNLOCK_SETTINGS);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_FIRST_SETUP) {
            if (resultCode != RESULT_OK) {
                finish();
                return;
            }
            verified = true;
            buildMainUi();
            showFirstRunHelp();
        } else if (requestCode == REQ_UNLOCK_SETTINGS) {
            if (resultCode != RESULT_OK) {
                finish();
                return;
            }
            verified = true;
            buildMainUi();
        } else if (requestCode == REQ_CHANGE_CREDENTIAL) {
            if (resultCode == RESULT_OK) {
                Toast.makeText(this, "Lock method updated", Toast.LENGTH_SHORT).show();
            }
            refreshStatus();
        } else if (requestCode == REQ_BACKGROUND
                && resultCode == RESULT_OK
                && data != null
                && data.getData() != null) {
            Uri uri = data.getData();
            try {
                int flags = data.getFlags()
                        & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                getContentResolver().takePersistableUriPermission(
                        uri,
                        flags & Intent.FLAG_GRANT_READ_URI_PERMISSION
                );
            } catch (Exception ignored) {}
            Prefs.setBackgroundUri(this, uri.toString());
            Toast.makeText(this, "Background updated", Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (verified) {
            if (Prefs.isProtectionEnabled(this) && UsageLockService.hasRequiredAccess(this)) {
                UsageLockService.ensureRunning(this);
            }
            refreshStatus();
        }
    }

    private void buildMainUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(22), dp(18), dp(28));
        root.setBackgroundColor(Color.rgb(18, 18, 18));
        scroll.addView(root, new ScrollView.LayoutParams(-1, -2));

        TextView title = text("Lock by Isril", 28, Color.WHITE);
        root.addView(title, new LinearLayout.LayoutParams(-1, -2));

        statusText = text("", 15, Color.LTGRAY);
        LinearLayout.LayoutParams stp = new LinearLayout.LayoutParams(-1, -2);
        stp.topMargin = dp(6);
        root.addView(statusText, stp);

        protectionSwitch = new Switch(this);
        protectionSwitch.setText("Protection");
        protectionSwitch.setTextColor(Color.WHITE);
        protectionSwitch.setTextSize(19);
        LinearLayout.LayoutParams ps = new LinearLayout.LayoutParams(-1, dp(64));
        ps.topMargin = dp(18);
        root.addView(protectionSwitch, ps);
        protectionSwitch.setChecked(Prefs.isProtectionEnabled(this));
        protectionSwitch.setOnCheckedChangeListener((buttonView, isChecked) -> {
            Prefs.setProtectionEnabled(this, isChecked);
            SessionManager.clearAll();

            if (isChecked) {
                if (UsageLockService.hasRequiredAccess(this)) {
                    UsageLockService.ensureRunning(this);
                } else {
                    showAccessNeededDialog();
                }
            } else {
                UsageLockService.stopRunning(this);
            }
            refreshStatus();
        });

        addSection(root, "Apps");
        Button apps = button("Choose locked apps");
        root.addView(apps, fullButtonParams());
        apps.setOnClickListener(v -> startActivity(new Intent(this, AppPickerActivity.class)));

        addSection(root, "Unlock");
        Button method = button("Lock method");
        root.addView(method, fullButtonParams());
        method.setOnClickListener(v -> chooseMethod());

        Switch biometric = new Switch(this);
        biometric.setText("Fingerprint");
        biometric.setTextColor(Color.WHITE);
        biometric.setChecked(Prefs.isBiometricEnabled(this) && canUseBiometric());
        biometric.setEnabled(canUseBiometric());
        root.addView(biometric, new LinearLayout.LayoutParams(-1, dp(56)));
        biometric.setOnCheckedChangeListener((buttonView, isChecked) ->
                Prefs.setBiometricEnabled(this, isChecked));

        Switch lines = new Switch(this);
        lines.setText("Show pattern lines");
        lines.setTextColor(Color.WHITE);
        lines.setChecked(Prefs.showPatternLines(this));
        root.addView(lines, new LinearLayout.LayoutParams(-1, dp(56)));
        lines.setOnCheckedChangeListener((buttonView, isChecked) ->
                Prefs.setShowPatternLines(this, isChecked));

        Switch touches = new Switch(this);
        touches.setText("Highlight touched dots");
        touches.setTextColor(Color.WHITE);
        touches.setChecked(Prefs.showPatternTouches(this));
        root.addView(touches, new LinearLayout.LayoutParams(-1, dp(56)));
        touches.setOnCheckedChangeListener((buttonView, isChecked) ->
                Prefs.setShowPatternTouches(this, isChecked));

        Switch haptic = new Switch(this);
        haptic.setText("Vibrate while drawing pattern");
        haptic.setTextColor(Color.WHITE);
        haptic.setChecked(Prefs.patternHaptic(this));
        root.addView(haptic, new LinearLayout.LayoutParams(-1, dp(56)));
        haptic.setOnCheckedChangeListener((buttonView, isChecked) ->
                Prefs.setPatternHaptic(this, isChecked));

        addSection(root, "Lock timing");
        Button auto = button("Auto lock timing");
        root.addView(auto, fullButtonParams());
        auto.setOnClickListener(v -> chooseAutoLock());

        Button temp = button("Temporary unlock");
        root.addView(temp, fullButtonParams());
        temp.setOnClickListener(v -> chooseTemporaryUnlock());

        addSection(root, "Appearance");
        Button background = button("Choose lock background");
        root.addView(background, fullButtonParams());
        background.setOnClickListener(v -> chooseBackground());

        Button resetBg = button("Use original background");
        root.addView(resetBg, fullButtonParams());
        resetBg.setOnClickListener(v -> {
            Prefs.setBackgroundUri(this, null);
            Toast.makeText(this, "Original background restored", Toast.LENGTH_SHORT).show();
        });

        Button dim = button("Background darkness");
        root.addView(dim, fullButtonParams());
        dim.setOnClickListener(v -> chooseDim());

        addSection(root, "Required Android access");
        accessText = text("", 14, Color.LTGRAY);
        LinearLayout.LayoutParams ap = new LinearLayout.LayoutParams(-1, -2);
        ap.bottomMargin = dp(8);
        root.addView(accessText, ap);

        Button usage = button("Open Usage access");
        root.addView(usage, fullButtonParams());
        usage.setOnClickListener(v -> openUsageAccess());

        Button overlay = button("Open Appear on top");
        root.addView(overlay, fullButtonParams());
        overlay.setOnClickListener(v -> openOverlayAccess());

        Button appInfo = button("Open App info");
        root.addView(appInfo, fullButtonParams());
        appInfo.setOnClickListener(v -> {
            Intent i = new Intent(
                    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + getPackageName())
            );
            startActivity(i);
        });

        TextView privacy = text(
                "No Accessibility service is used. App detection uses local Usage access. No account, ads, analytics, location, camera, microphone, or internet access is used by this app.",
                13,
                Color.GRAY
        );
        LinearLayout.LayoutParams pp = new LinearLayout.LayoutParams(-1, -2);
        pp.topMargin = dp(22);
        root.addView(privacy, pp);

        setContentView(scroll);
        refreshStatus();
    }

    private void refreshStatus() {
        if (statusText == null) return;

        Set<String> locked = Prefs.getLockedApps(this);
        long temp = Prefs.getTemporaryOffUntil(this);

        boolean usage = UsageLockService.isUsageAccessGranted(this);
        boolean overlay = UsageLockService.isOverlayGranted(this);

        String state;
        if (!Prefs.isProtectionEnabled(this)) {
            state = "Protection OFF";
        } else if (!usage || !overlay) {
            state = "Protection ON • Android access missing";
        } else if (temp > System.currentTimeMillis()) {
            state = "Protection temporarily paused";
        } else {
            state = "Protection ON";
        }

        statusText.setText(state + "  •  " + locked.size() + " apps selected");

        if (protectionSwitch != null
                && protectionSwitch.isChecked() != Prefs.isProtectionEnabled(this)) {
            protectionSwitch.setChecked(Prefs.isProtectionEnabled(this));
        }

        if (accessText != null) {
            String usageText = usage ? "Usage access ON" : "Usage access OFF";
            String overlayText = overlay ? "Appear on top ON" : "Appear on top OFF";
            accessText.setText(
                    usageText + "\n"
                            + overlayText + "\n"
                            + "Accessibility is not used in this version."
            );
        }
    }

    private void chooseMethod() {
        String[] options = {"Pattern", "PIN"};
        new AlertDialog.Builder(this)
                .setTitle("Choose lock method")
                .setItems(options, (dialog, which) -> {
                    String method = which == 0 ? Prefs.METHOD_PATTERN : Prefs.METHOD_PIN;
                    Intent i = new Intent(this, SetupCredentialActivity.class);
                    i.putExtra(SetupCredentialActivity.EXTRA_METHOD, method);
                    startActivityForResult(i, REQ_CHANGE_CREDENTIAL);
                })
                .show();
    }

    private void chooseAutoLock() {
        String[] options = {
                "Immediately after leaving",
                "After 30 seconds",
                "After 1 minute",
                "After 5 minutes",
                "After 10 minutes"
        };
        long[] values = {0L, 30_000L, 60_000L, 300_000L, 600_000L};

        new AlertDialog.Builder(this)
                .setTitle("Auto lock")
                .setItems(options, (dialog, which) -> {
                    Prefs.setAutoLockDelay(this, values[which]);
                    SessionManager.clearAll();
                    Toast.makeText(this, options[which], Toast.LENGTH_SHORT).show();
                })
                .show();
    }

    private void chooseTemporaryUnlock() {
        String[] options = {
                "10 minutes",
                "30 minutes",
                "1 hour",
                "Until I turn protection on again",
                "Cancel temporary unlock"
        };

        new AlertDialog.Builder(this)
                .setTitle("Temporary unlock")
                .setItems(options, (dialog, which) -> {
                    long now = System.currentTimeMillis();

                    if (which == 0) {
                        Prefs.setTemporaryOffUntil(this, now + 10 * 60_000L);
                    } else if (which == 1) {
                        Prefs.setTemporaryOffUntil(this, now + 30 * 60_000L);
                    } else if (which == 2) {
                        Prefs.setTemporaryOffUntil(this, now + 60 * 60_000L);
                    } else if (which == 3) {
                        Prefs.setProtectionEnabled(this, false);
                        UsageLockService.stopRunning(this);
                    } else {
                        Prefs.setTemporaryOffUntil(this, 0L);
                    }

                    SessionManager.clearAll();
                    refreshStatus();
                })
                .show();
    }

    private void chooseBackground() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("image/*");
        i.addFlags(
                Intent.FLAG_GRANT_READ_URI_PERMISSION
                        | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        );
        startActivityForResult(i, REQ_BACKGROUND);
    }

    private void chooseDim() {
        String[] options = {"Normal", "Slightly dark", "Darker"};
        new AlertDialog.Builder(this)
                .setTitle("Background darkness")
                .setSingleChoiceItems(
                        options,
                        Prefs.getBackgroundDim(this),
                        (dialog, which) -> {
                            Prefs.setBackgroundDim(this, which);
                            dialog.dismiss();
                        }
                )
                .show();
    }

    private boolean canUseBiometric() {
        if (Build.VERSION.SDK_INT < 28) return false;
        PackageManager pm = getPackageManager();
        boolean feature = pm.hasSystemFeature(PackageManager.FEATURE_FINGERPRINT);
        KeyguardManager km = getSystemService(KeyguardManager.class);
        return feature && km != null && km.isDeviceSecure();
    }

    private void showFirstRunHelp() {
        new AlertDialog.Builder(this)
                .setTitle("Two Android settings are required")
                .setMessage(
                        "This version does not use Accessibility. Enable Usage access so Lock by Isril can detect the foreground app, then enable Appear on top so the lock screen can cover protected apps."
                )
                .setPositiveButton("Usage access", (d, w) -> openUsageAccess())
                .setNeutralButton("Appear on top", (d, w) -> openOverlayAccess())
                .setNegativeButton("Later", null)
                .show();
    }

    private void showAccessNeededDialog() {
        boolean usage = UsageLockService.isUsageAccessGranted(this);
        boolean overlay = UsageLockService.isOverlayGranted(this);

        String message;
        if (!usage && !overlay) {
            message = "Protection needs Usage access and Appear on top. Accessibility is not used.";
        } else if (!usage) {
            message = "Protection needs Usage access. Accessibility is not used.";
        } else {
            message = "Protection needs Appear on top. Accessibility is not used.";
        }

        new AlertDialog.Builder(this)
                .setTitle("Android access required")
                .setMessage(message)
                .setPositiveButton(!usage ? "Open Usage access" : "Open Appear on top",
                        (d, w) -> {
                            if (!usage) openUsageAccess();
                            else openOverlayAccess();
                        })
                .setNegativeButton("Later", null)
                .show();
    }

    private void openUsageAccess() {
        try {
            Intent i = new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS);
            i.setData(Uri.parse("package:" + getPackageName()));
            startActivity(i);
        } catch (Exception first) {
            try {
                startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
            } catch (Exception second) {
                Toast.makeText(this, "Could not open Usage access settings", Toast.LENGTH_SHORT).show();
            }
        }
    }

    private void openOverlayAccess() {
        try {
            Intent i = new Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName())
            );
            startActivity(i);
        } catch (Exception e) {
            Toast.makeText(this, "Could not open Appear on top settings", Toast.LENGTH_SHORT).show();
        }
    }

    private void addSection(LinearLayout root, String label) {
        TextView t = text(label, 15, Color.GRAY);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2);
        p.topMargin = dp(22);
        p.bottomMargin = dp(5);
        root.addView(t, p);
    }

    private LinearLayout.LayoutParams fullButtonParams() {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(54));
        p.bottomMargin = dp(7);
        return p;
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        return t;
    }

    private Button button(String s) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        b.setPadding(dp(16), 0, dp(16), 0);
        return b;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
''', encoding="utf-8")

# Clean up the old Accessibility description so the final source no longer describes that permission.
strings = root / "app/src/main/res/values/strings.xml"
strings.write_text(r'''<resources>
    <string name="app_name">Lock by Isril</string>
</resources>
''', encoding="utf-8")

# Version 1.5.
gradle = root / "app/build.gradle"
text = gradle.read_text(encoding="utf-8")
text = text.replace("versionCode 5", "versionCode 6")
text = text.replace("versionName '1.4'", "versionName '1.5'")
gradle.write_text(text, encoding="utf-8")

print("Lock by Isril v1.5 Usage Access + overlay architecture applied")
