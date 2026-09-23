from pathlib import Path

root = Path("extracted/LockByIsril")

def replace_once(path, old, new):
    p = root / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected text not found in {path}: {old[:80]}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")

# 1. Allow the app picker to see all launchable installed apps on Android 11+.
manifest = root / "app/src/main/AndroidManifest.xml"
text = manifest.read_text(encoding="utf-8")
permission = '    <uses-permission android:name="android.permission.QUERY_ALL_PACKAGES" />\n'
if "android.permission.QUERY_ALL_PACKAGES" not in text:
    marker = '    <uses-permission android:name="android.permission.USE_BIOMETRIC" />\n'
    text = text.replace(marker, permission + marker, 1)
manifest.write_text(text, encoding="utf-8")

# 2. The first credential setup must respect the hidden-pattern-lines default.
setup = root / "app/src/main/java/com/isril/lockbyisril/SetupCredentialActivity.java"
text = setup.read_text(encoding="utf-8")
text = text.replace("patternView.setShowLines(true);", "patternView.setShowLines(Prefs.showPatternLines(this));")
text = text.replace("patternView.setShowTouches(true);", "patternView.setShowTouches(Prefs.showPatternTouches(this));")
text = text.replace("patternView.setHaptic(true);", "patternView.setHaptic(Prefs.patternHaptic(this));")
setup.write_text(text, encoding="utf-8")

# 3. Use PackageManager with QUERY_ALL_PACKAGES so every launchable app is listed.
picker = root / "app/src/main/java/com/isril/lockbyisril/AppPickerActivity.java"
picker.write_text(r'''package com.isril.lockbyisril;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
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

public class AppPickerActivity extends Activity {
    private final List<AppEntry> apps = new ArrayList<>();
    private Set<String> selected;
    private LinearLayout list;

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
        loadApps();
        buildUi();
    }

    private void loadApps() {
        PackageManager pm = getPackageManager();
        Map<String, AppEntry> unique = new HashMap<>();

        try {
            List<ApplicationInfo> installed = pm.getInstalledApplications(PackageManager.GET_META_DATA);
            for (ApplicationInfo info : installed) {
                String pkg = info.packageName;
                if (pkg == null || pkg.equals(getPackageName())) continue;

                Intent launchIntent = pm.getLaunchIntentForPackage(pkg);
                if (launchIntent == null) continue;

                String label;
                Drawable icon;
                try {
                    CharSequence cs = info.loadLabel(pm);
                    label = cs == null ? pkg : cs.toString();
                } catch (Exception e) {
                    label = pkg;
                }
                try {
                    icon = info.loadIcon(pm);
                } catch (Exception e) {
                    icon = pm.getDefaultActivityIcon();
                }

                unique.put(pkg, new AppEntry(pkg, label, icon));
            }
        } catch (Exception ignored) {
        }

        apps.clear();
        apps.addAll(unique.values());
        apps.sort(Comparator.comparing(a -> a.label.toLowerCase(Locale.getDefault())));
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

        TextView count = new TextView(this);
        count.setText(apps.size() + " apps available");
        count.setTextSize(13);
        count.setTextColor(Color.GRAY);
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(-1, -2);
        cp.topMargin = dp(4);
        root.addView(count, cp);

        EditText search = new EditText(this);
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

        render("");
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

# 4. Listen for both main window transition event types.
config = root / "app/src/main/res/xml/accessibility_service_config.xml"
text = config.read_text(encoding="utf-8")
text = text.replace(
    'android:accessibilityEventTypes="typeWindowStateChanged"',
    'android:accessibilityEventTypes="typeWindowStateChanged|typeWindowsChanged"'
)
config.write_text(text, encoding="utf-8")

# 5. Make Accessibility state obvious in the main status line.
main = root / "app/src/main/java/com/isril/lockbyisril/MainActivity.java"
text = main.read_text(encoding="utf-8")
old = 'statusText.setText(state + "  •  " + locked.size() + " apps selected");'
new = '''if (Prefs.isProtectionEnabled(this) && !isAccessibilityEnabled()) {
            state = "Protection ON • Accessibility OFF";
        }
        statusText.setText(state + "  •  " + locked.size() + " apps selected");'''
if old in text:
    text = text.replace(old, new, 1)
main.write_text(text, encoding="utf-8")

# 6. Version bump.
gradle = root / "app/build.gradle"
text = gradle.read_text(encoding="utf-8")
text = text.replace("versionCode 1", "versionCode 2")
text = text.replace("versionName '1.0'", "versionName '1.1'")
gradle.write_text(text, encoding="utf-8")

print("Lock by Isril v1.1 fixes applied")
