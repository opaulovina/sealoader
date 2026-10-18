package io.github.opaulovina.sealoader;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.JavascriptInterface;
import android.webkit.MimeTypeMap;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URLDecoder;
import java.net.URLEncoder;
import java.util.HashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Sealoader para Android: a mesma interface do site (web/), embutida no APK e servida no
 * endereço do GitHub Pages, então ela encontra o servidor da casa exatamente como o site.
 * O que o WebView não faz sozinho (salvar arquivos, colar, compartilhar) passa pela ponte
 * {@code window.SealoaderAndroid}.
 */
public class MainActivity extends Activity {
    private static final String HOST = "opaulovina.github.io";
    private static final String PREFIX = "/sealoader/";
    private static final String HOME = "https://" + HOST + PREFIX;
    private static final int PICK_FILE = 1;
    private static final Pattern URL_IN_TEXT = Pattern.compile("https?://\\S+");

    private WebView web;
    private ValueCallback<Uri[]> fileCallback;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        setContentView(web);

        // Android 15+ draws edge to edge: keep the page clear of the status and navigation bars
        web.setOnApplyWindowInsetsListener((v, insets) -> {
            android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return WindowInsets.CONSUMED;
        });

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setSupportZoom(false);
        s.setUserAgentString(s.getUserAgentString() + " SealoaderAndroid");
        web.setBackgroundColor(0xFFFFFFFF);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.addJavascriptInterface(new Bridge(), "SealoaderAndroid");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (!HOST.equals(u.getHost()) || u.getPath() == null || !u.getPath().startsWith(PREFIX)) return null;
                String path = u.getPath().substring(PREFIX.length());
                if (path.isEmpty()) path = "index.html";
                try {
                    InputStream in = getAssets().open(path);
                    String ext = MimeTypeMap.getFileExtensionFromUrl(path);
                    String mime = "webmanifest".equals(ext) ? "application/manifest+json"
                            : MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
                    Map<String, String> headers = new HashMap<>();
                    headers.put("Cache-Control", "no-cache");
                    return new WebResourceResponse(mime == null ? "application/octet-stream" : mime, "utf-8", 200, "OK", headers, in);
                } catch (IOException e) {
                    return null;
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                String path = u.getPath() == null ? "" : u.getPath();
                if (HOST.equals(u.getHost()) && path.startsWith(PREFIX)) return false;
                if (path.startsWith("/api/")) return false;   // file downloads from the server
                startActivity(new Intent(Intent.ACTION_VIEW, u));
                return true;
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), PICK_FILE);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });

        web.setDownloadListener((url, userAgent, disposition, mime, length) -> {
            String name = fileName(disposition, url, mime);
            DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url))
                    .setTitle(name)
                    .setMimeType(mime)
                    .addRequestHeader("User-Agent", userAgent)
                    .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                    .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "Sealoader/" + name);
            ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(r);
            toast("Salvando em Downloads/Sealoader");
        });

        if (state != null) web.restoreState(state);
        else web.loadUrl(startUrl(getIntent()));
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String shared = sharedUrl(intent);
        if (shared != null) web.loadUrl(startUrl(intent));
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == PICK_FILE && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            fileCallback = null;
        }
    }

    private String startUrl(Intent intent) {
        String shared = sharedUrl(intent);
        if (shared == null) return HOME;
        try {
            return HOME + "?url=" + URLEncoder.encode(shared, "UTF-8");
        } catch (Exception e) {
            return HOME;
        }
    }

    private static String sharedUrl(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) return null;
        String text = intent.getStringExtra(Intent.EXTRA_TEXT);
        if (text == null) return null;
        Matcher m = URL_IN_TEXT.matcher(text);
        return m.find() ? m.group() : null;
    }

    /** Prefer the UTF-8 filename* the server sends, so accents and emoji survive. */
    private static String fileName(String disposition, String url, String mime) {
        if (disposition != null) {
            Matcher m = Pattern.compile("filename\\*=UTF-8''([^;]+)", Pattern.CASE_INSENSITIVE).matcher(disposition);
            if (m.find()) {
                try {
                    return clean(URLDecoder.decode(m.group(1), "UTF-8"));
                } catch (Exception ignored) {
                }
            }
            m = Pattern.compile("filename=\"?([^\";]+)\"?", Pattern.CASE_INSENSITIVE).matcher(disposition);
            if (m.find()) return clean(m.group(1));
        }
        return clean(URLUtil.guessFileName(url, disposition, mime));
    }

    private static String clean(String name) {
        return name.replaceAll("[\\\\/:*?\"<>|]", "_");
    }

    private void toast(String msg) {
        runOnUiThread(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
    }

    private Uri saveToMediaStore(String name, String mime, byte[] bytes, boolean image) throws IOException {
        ContentResolver cr = getContentResolver();
        ContentValues v = new ContentValues();
        v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
        v.put(MediaStore.MediaColumns.MIME_TYPE, mime);
        v.put(MediaStore.MediaColumns.RELATIVE_PATH, (image ? Environment.DIRECTORY_PICTURES : Environment.DIRECTORY_DOWNLOADS) + "/Sealoader");
        Uri collection = image ? MediaStore.Images.Media.EXTERNAL_CONTENT_URI : MediaStore.Downloads.EXTERNAL_CONTENT_URI;
        Uri uri = cr.insert(collection, v);
        if (uri == null) throw new IOException("sem acesso ao armazenamento");
        try (OutputStream out = cr.openOutputStream(uri)) {
            if (out == null) throw new IOException("sem acesso ao armazenamento");
            out.write(bytes);
        }
        return uri;
    }

    /** Exposed to the page as window.SealoaderAndroid. */
    private class Bridge {
        @JavascriptInterface
        public String getClipboard() {
            ClipboardManager cm = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
            ClipData clip = cm.getPrimaryClip();
            if (clip == null || clip.getItemCount() == 0) return "";
            CharSequence t = clip.getItemAt(0).coerceToText(MainActivity.this);
            return t == null ? "" : t.toString();
        }

        @JavascriptInterface
        public void saveBase64(String name, String mime, String b64) {
            try {
                // PNGs go to the gallery (Pictures/Sealoader), anything else to Downloads/Sealoader
                boolean image = mime.startsWith("image/png");
                saveToMediaStore(name, mime, Base64.decode(b64, Base64.DEFAULT), image);
                toast(image ? "QR code salvo na galeria" : "Salvo em Downloads/Sealoader");
            } catch (Exception e) {
                toast("Não deu para salvar: " + e.getMessage());
            }
        }

        @JavascriptInterface
        public void shareImage(String name, String b64) {
            try {
                Uri uri = saveToMediaStore(name, "image/png", Base64.decode(b64, Base64.DEFAULT), true);
                Intent send = new Intent(Intent.ACTION_SEND)
                        .setType("image/png")
                        .putExtra(Intent.EXTRA_STREAM, uri)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                runOnUiThread(() -> startActivity(Intent.createChooser(send, "Enviar QR code")));
            } catch (Exception e) {
                toast("Não deu para compartilhar: " + e.getMessage());
            }
        }
    }
}
