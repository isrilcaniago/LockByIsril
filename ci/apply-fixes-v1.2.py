from pathlib import Path

root = Path("extracted/LockByIsril")

# Add a marker for PINs created under the new fixed 6 digit flow.
prefs = root / "app/src/main/java/com/isril/lockbyisril/Prefs.java"
text = prefs.read_text(encoding="utf-8")
if 'K_PIN_SIX' not in text:
    text = text.replace(
        '    private static final String K_LOCKOUT = "lockout_until";\n',
        '    private static final String K_LOCKOUT = "lockout_until";\n'
        '    private static final String K_PIN_SIX = "pin_six_digit_configured";\n'
    )
    text = text.replace(
        '    public static void setLockoutUntil(Context c, long t) { p(c).edit().putLong(K_LOCKOUT, t).apply(); }\n',
        '    public static void setLockoutUntil(Context c, long t) { p(c).edit().putLong(K_LOCKOUT, t).apply(); }\n'
        '    public static boolean isPinSixDigitConfigured(Context c) { return p(c).getBoolean(K_PIN_SIX, false); }\n'
        '    public static void setPinSixDigitConfigured(Context c, boolean v) { p(c).edit().putBoolean(K_PIN_SIX, v).apply(); }\n'
    )
prefs.write_text(text, encoding="utf-8")

# Fixed 6 digit PIN setup. No Continue or OK button.
setup = root / "app/src/main/java/com/isril/lockbyisril/SetupCredentialActivity.java"
setup.write_text(r'''package com.isril.lockbyisril;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.text.Editable;
import android.text.InputFilter;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

public class SetupCredentialActivity extends Activity {
    public static final String EXTRA_METHOD = "method";
    private String method;
    private String first;
    private TextView title;
    private PatternView patternView;
    private EditText pinInput;
    private boolean processingPin;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
        method = getIntent().getStringExtra(EXTRA_METHOD);
        if (!Prefs.METHOD_PIN.equals(method)) method = Prefs.METHOD_PATTERN;
        buildUi();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(dp(24), dp(48), dp(24), dp(24));
        root.setBackgroundColor(Color.BLACK);

        TextView app = text("Lock by Isril", 26, Color.WHITE);
        app.setGravity(Gravity.CENTER);
        root.addView(app, new LinearLayout.LayoutParams(-1, -2));

        title = text(Prefs.METHOD_PATTERN.equals(method) ? "Draw a new pattern" : "Enter a new 6 digit PIN", 18, Color.LTGRAY);
        title.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(-1, -2);
        tp.topMargin = dp(28);
        root.addView(title, tp);

        if (Prefs.METHOD_PATTERN.equals(method)) buildPattern(root);
        else buildPin(root);

        setContentView(root);
    }

    private void buildPattern(LinearLayout root) {
        patternView = new PatternView(this);
        patternView.setShowLines(Prefs.showPatternLines(this));
        patternView.setShowTouches(Prefs.showPatternTouches(this));
        patternView.setHaptic(Prefs.patternHaptic(this));
        LinearLayout.LayoutParams pp = new LinearLayout.LayoutParams(dp(320), dp(320));
        pp.topMargin = dp(32);
        root.addView(patternView, pp);
        patternView.setListener(this::onPattern);
    }

    private void onPattern(List<Integer> pattern) {
        if (pattern.size() < 4) {
            title.setText("Use at least 4 dots");
            patternView.showError();
            return;
        }
        String value = PatternView.serialize(pattern);
        if (first == null) {
            first = value;
            title.setText("Draw the same pattern again");
            patternView.clearPattern();
            return;
        }
        if (!first.equals(value)) {
            first = null;
            title.setText("Patterns did not match. Try again");
            patternView.showError();
            return;
        }
        save(value);
    }

    private void buildPin(LinearLayout root) {
        pinInput = new EditText(this);
        pinInput.setTextColor(Color.WHITE);
        pinInput.setHintTextColor(Color.GRAY);
        pinInput.setHint("6 digits");
        pinInput.setGravity(Gravity.CENTER);
        pinInput.setTextSize(26);
        pinInput.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        pinInput.setFilters(new InputFilter[]{new InputFilter.LengthFilter(6)});
        LinearLayout.LayoutParams ep = new LinearLayout.LayoutParams(-1, dp(72));
        ep.topMargin = dp(36);
        root.addView(pinInput, ep);

        TextView help = text("Automatically continues after the sixth digit", 13, Color.GRAY);
        help.setGravity(Gravity.CENTER);
        root.addView(help, new LinearLayout.LayoutParams(-1, -2));

        pinInput.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {}
            @Override public void afterTextChanged(Editable s) {
                if (!processingPin && s.length() == 6) {
                    pinInput.post(SetupCredentialActivity.this::onPinComplete);
                }
            }
        });
        pinInput.requestFocus();
    }

    private void onPinComplete() {
        if (processingPin) return;
        String value = pinInput.getText().toString();
        if (value.length() != 6) return;

        processingPin = true;
        if (first == null) {
            first = value;
            pinInput.setText("");
            title.setText("Enter the same 6 digit PIN again");
            processingPin = false;
            return;
        }

        if (!first.equals(value)) {
            first = null;
            pinInput.setText("");
            title.setText("PINs did not match. Try again");
            processingPin = false;
            return;
        }

        save(value);
    }

    private void save(String value) {
        if (!CredentialStore.save(this, value)) {
            processingPin = false;
            Toast.makeText(this, "Could not save the lock credential", Toast.LENGTH_LONG).show();
            return;
        }
        Prefs.setMethod(this, method);
        if (Prefs.METHOD_PIN.equals(method)) Prefs.setPinSixDigitConfigured(this, true);
        Prefs.setSetupComplete(this, true);
        setResult(RESULT_OK);
        finish();
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        return t;
    }

    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }
}
''', encoding="utf-8")

# Lock screen: fixed 6 digit PIN, auto unlock, centered keypad, and no attempt limit.
lock = root / "app/src/main/java/com/isril/lockbyisril/LockActivity.java"
lock.write_text(r'''package com.isril.lockbyisril;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Intent;
import android.graphics.Color;
import android.hardware.biometrics.BiometricPrompt;
import android.net.Uri;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
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

public class LockActivity extends Activity {
    public static final String EXTRA_TARGET = "target_package";
    public static final String EXTRA_MODE = "mode";
    public static final String MODE_SETTINGS = "settings";
    public static volatile boolean visible = false;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private String targetPackage;
    private boolean settingsMode;
    private TextView message;
    private PatternView patternView;
    private TextView pinDots;
    private final StringBuilder pin = new StringBuilder();
    private CancellationSignal biometricCancel;
    private boolean legacyPinMode;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        visible = true;
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
        targetPackage = getIntent().getStringExtra(EXTRA_TARGET);
        settingsMode = MODE_SETTINGS.equals(getIntent().getStringExtra(EXTRA_MODE));
        legacyPinMode = Prefs.METHOD_PIN.equals(Prefs.getMethod(this)) && !Prefs.isPinSixDigitConfigured(this);
        buildUi();
        if (Prefs.isBiometricEnabled(this)) handler.postDelayed(this::authenticateFingerprint, 350);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        targetPackage = intent.getStringExtra(EXTRA_TARGET);
        settingsMode = MODE_SETTINGS.equals(intent.getStringExtra(EXTRA_MODE));
    }

    private void buildUi() {
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

        message = text(Prefs.METHOD_PIN.equals(Prefs.getMethod(this)) ? "Enter PIN" : "Draw pattern", 17, Color.LTGRAY);
        message.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams mp = new LinearLayout.LayoutParams(-1, -2);
        mp.topMargin = dp(12);
        content.addView(message, mp);

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

        setContentView(root);
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
        String value = PatternView.serialize(pattern);
        if (CredentialStore.verify(this, value)) success();
        else {
            message.setText("Wrong pattern");
            patternView.showError();
        }
    }

    private void buildPin(LinearLayout content) {
        LinearLayout pinArea = new LinearLayout(this);
        pinArea.setOrientation(LinearLayout.VERTICAL);
        pinArea.setGravity(Gravity.CENTER_HORIZONTAL);

        pinDots = text("", 27, Color.WHITE);
        pinDots.setGravity(Gravity.CENTER);
        pinArea.addView(pinDots, new LinearLayout.LayoutParams(-1, dp(50)));
        updatePinDots();

        GridLayout grid = new GridLayout(this);
        grid.setColumnCount(3);
        grid.setRowCount(4);

        String[] labels = legacyPinMode
                ? new String[]{"1","2","3","4","5","6","7","8","9","⌫","0","OK"}
                : new String[]{"1","2","3","4","5","6","7","8","9","","0","⌫"};

        for (String label : labels) {
            if (label.isEmpty()) {
                View empty = new View(this);
                GridLayout.LayoutParams ep = new GridLayout.LayoutParams();
                ep.width = dp(84);
                ep.height = dp(60);
                ep.setMargins(dp(4), dp(4), dp(4), dp(4));
                grid.addView(empty, ep);
                continue;
            }

            Button b = new Button(this);
            b.setText(label);
            b.setTextSize(19);
            b.setAllCaps(false);
            GridLayout.LayoutParams gp = new GridLayout.LayoutParams();
            gp.width = dp(84);
            gp.height = dp(60);
            gp.setMargins(dp(4), dp(4), dp(4), dp(4));
            grid.addView(b, gp);

            if ("⌫".equals(label)) b.setOnClickListener(v -> backspacePin());
            else if ("OK".equals(label)) b.setOnClickListener(v -> submitPin());
            else b.setOnClickListener(v -> addPin(label));
        }

        LinearLayout.LayoutParams gp = new LinearLayout.LayoutParams(-2, -2);
        gp.gravity = Gravity.CENTER_HORIZONTAL;
        pinArea.addView(grid, gp);

        LinearLayout.LayoutParams areaParams = new LinearLayout.LayoutParams(-1, -2);
        areaParams.gravity = Gravity.CENTER_HORIZONTAL;
        content.addView(pinArea, areaParams);
    }

    private void addPin(String digit) {
        int max = legacyPinMode ? 8 : 6;
        if (pin.length() >= max) return;
        pin.append(digit);
        updatePinDots();

        if (!legacyPinMode && pin.length() == 6) {
            handler.postDelayed(this::submitPin, 80);
        }
    }

    private void backspacePin() {
        if (pin.length() > 0) pin.deleteCharAt(pin.length() - 1);
        updatePinDots();
        message.setText("Enter PIN");
    }

    private void updatePinDots() {
        if (pinDots == null) return;
        if (legacyPinMode) {
            StringBuilder s = new StringBuilder();
            for (int i = 0; i < pin.length(); i++) {
                if (i > 0) s.append("  ");
                s.append("●");
            }
            pinDots.setText(s.toString());
            return;
        }

        StringBuilder s = new StringBuilder();
        for (int i = 0; i < 6; i++) {
            if (i > 0) s.append("  ");
            s.append(i < pin.length() ? "●" : "○");
        }
        pinDots.setText(s.toString());
    }

    private void submitPin() {
        if (!legacyPinMode && pin.length() != 6) return;
        if (legacyPinMode && (pin.length() < 4 || pin.length() > 8)) return;

        if (CredentialStore.verify(this, pin.toString())) {
            success();
        } else {
            pin.setLength(0);
            updatePinDots();
            message.setText("Wrong PIN");
        }
    }

    private void success() {
        if (settingsMode) {
            setResult(RESULT_OK);
        } else {
            SessionManager.markUnlocked(targetPackage);
        }
        finish();
    }

    private void authenticateFingerprint() {
        if (!Prefs.isBiometricEnabled(this) || android.os.Build.VERSION.SDK_INT < 28) return;
        try {
            KeyguardManager km = getSystemService(KeyguardManager.class);
            if (km == null || !km.isDeviceSecure()) {
                message.setText("Set a device screen lock before using fingerprint");
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
                    success();
                }

                @Override
                public void onAuthenticationFailed() {
                    super.onAuthenticationFailed();
                    message.setText("Fingerprint not recognized");
                }
            });
        } catch (Exception e) {
            message.setText("Fingerprint is not available");
        }
    }

    @Override
    public void onBackPressed() {
        if (settingsMode) {
            setResult(RESULT_CANCELED);
            finish();
            return;
        }
        Intent home = new Intent(Intent.ACTION_MAIN);
        home.addCategory(Intent.CATEGORY_HOME);
        home.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(home);
        finish();
    }

    @Override
    protected void onDestroy() {
        if (biometricCancel != null) biometricCancel.cancel();
        visible = false;
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        return t;
    }

    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }
}
''', encoding="utf-8")

# Faster app list: open immediately, load in background, and cache results for later openings.
picker = root / "app/src/main/java/com/isril/lockbyisril/AppPickerActivity.java"
picker.write_text(r'''package com.isril.lockbyisril;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Color;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class AppPickerActivity extends Activity {
    private static volatile List<AppEntry> cachedApps = new ArrayList<>();

    private final List<AppEntry> apps = new ArrayList<>();
    private final ExecutorService loader = Executors.newSingleThreadExecutor();
    private Set<String> selected;
    private LinearLayout list;
    private TextView count;
    private EditText search;

    static class AppEntry {
        final String pkg;
        final String label;
        final Drawable icon;

        AppEntry(String pkg, String label, Drawable icon) {
            this.pkg = pkg;
            this.label = label;
            this.icon = icon;
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(18, 18, 18));
        getWindow().setNavigationBarColor(Color.BLACK);
        selected = new HashSet<>(Prefs.getLockedApps(this));

        buildUi();

        List<AppEntry> cache = cachedApps;
        if (cache != null && !cache.isEmpty()) {
            apps.addAll(cache);
            count.setText(apps.size() + " apps available");
            render("");
        } else {
            count.setText("Loading apps...");
        }

        loadAppsAsync();
    }

    @Override
    protected void onDestroy() {
        loader.shutdownNow();
        super.onDestroy();
    }

    private void loadAppsAsync() {
        loader.execute(() -> {
            List<AppEntry> loaded = scanApps();
            cachedApps = new ArrayList<>(loaded);
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                apps.clear();
                apps.addAll(loaded);
                count.setText(apps.size() + " apps available");
                render(search.getText().toString());
            });
        });
    }

    private List<AppEntry> scanApps() {
        PackageManager pm = getPackageManager();
        Map<String, AppEntry> unique = new HashMap<>();

        Intent launcher = new Intent(Intent.ACTION_MAIN);
        launcher.addCategory(Intent.CATEGORY_LAUNCHER);

        try {
            List<ResolveInfo> resolved = pm.queryIntentActivities(launcher, PackageManager.MATCH_ALL);
            for (ResolveInfo ri : resolved) {
                if (ri.activityInfo == null) continue;
                ApplicationInfo info = ri.activityInfo.applicationInfo;
                if (info == null) continue;

                String pkg = info.packageName;
                if (pkg == null || pkg.equals(getPackageName()) || unique.containsKey(pkg)) continue;

                String label;
                Drawable icon;
                try {
                    CharSequence cs = ri.loadLabel(pm);
                    label = cs == null ? pkg : cs.toString();
                } catch (Exception e) {
                    label = pkg;
                }
                try {
                    icon = ri.loadIcon(pm);
                    if (icon == null) icon = info.loadIcon(pm);
                } catch (Exception e) {
                    icon = pm.getDefaultActivityIcon();
                }

                unique.put(pkg, new AppEntry(pkg, label, icon));
            }
        } catch (Exception ignored) {
        }

        List<AppEntry> result = new ArrayList<>(unique.values());
        result.sort(Comparator.comparing(a -> a.label.toLowerCase(Locale.getDefault())));
        return result;
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(18, 18, 18));
        root.setPadding(dp(16), dp(18), dp(16), dp(12));

        TextView title = new TextView(this);
        title.setText("Locked apps");
        title.setTextSize(25);
        title.setTextColor(Color.WHITE);
        root.addView(title, new LinearLayout.LayoutParams(-1, -2));

        count = new TextView(this);
        count.setTextSize(13);
        count.setTextColor(Color.GRAY);
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(-1, -2);
        cp.topMargin = dp(4);
        root.addView(count, cp);

        search = new EditText(this);
        search.setHint("Search apps");
        search.setTextColor(Color.WHITE);
        search.setHintTextColor(Color.GRAY);
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(-1, dp(56));
        sp.topMargin = dp(8);
        root.addView(search, sp);

        ScrollView scroll = new ScrollView(this);
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(list, new ScrollView.LayoutParams(-1, -2));
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));

        search.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                render(s.toString());
            }
            @Override public void afterTextChanged(Editable s) {}
        });

        setContentView(root);
    }

    private void render(String query) {
        list.removeAllViews();
        String q = query.toLowerCase(Locale.getDefault()).trim();
        for (AppEntry app : apps) {
            if (!q.isEmpty()
                    && !app.label.toLowerCase(Locale.getDefault()).contains(q)
                    && !app.pkg.toLowerCase(Locale.getDefault()).contains(q)) {
                continue;
            }
            list.addView(row(app));
        }
    }

    private View row(AppEntry app) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(4), dp(8), dp(4), dp(8));

        ImageView icon = new ImageView(this);
        icon.setImageDrawable(app.icon);
        row.addView(icon, new LinearLayout.LayoutParams(dp(44), dp(44)));

        LinearLayout labels = new LinearLayout(this);
        labels.setOrientation(LinearLayout.VERTICAL);
        labels.setPadding(dp(12), 0, dp(8), 0);

        TextView name = new TextView(this);
        name.setText(app.label);
        name.setTextSize(17);
        name.setTextColor(Color.WHITE);
        labels.addView(name);

        TextView pkg = new TextView(this);
        pkg.setText(app.pkg);
        pkg.setTextSize(11);
        pkg.setTextColor(Color.GRAY);
        labels.addView(pkg);

        row.addView(labels, new LinearLayout.LayoutParams(0, -2, 1f));

        Switch sw = new Switch(this);
        sw.setChecked(selected.contains(app.pkg));
        sw.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (isChecked) selected.add(app.pkg);
            else selected.remove(app.pkg);
            Prefs.setLockedApps(this, selected);
            SessionManager.clearAll();
        });
        row.addView(sw, new LinearLayout.LayoutParams(-2, -2));
        return row;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
''', encoding="utf-8")

# Version 1.2.
gradle = root / "app/build.gradle"
text = gradle.read_text(encoding="utf-8")
text = text.replace("versionCode 2", "versionCode 3")
text = text.replace("versionName '1.1'", "versionName '1.2'")
gradle.write_text(text, encoding="utf-8")

print("Lock by Isril v1.2 fixes applied")
