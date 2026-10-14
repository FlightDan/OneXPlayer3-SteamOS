using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

public static class InstallerI18n
{
    public static string Language { get; private set; } = CultureInfo.CurrentUICulture.Name.StartsWith("zh", StringComparison.OrdinalIgnoreCase) ? "zh-CN" : "en-US";
    private static readonly Dictionary<string, string> English = JsonSerializer.Deserialize<Dictionary<string, string>>(
        File.ReadAllText(Path.Combine(Backend.Root, "components/i18n/en-US.json")))!;
    private static readonly System.Runtime.CompilerServices.ConditionalWeakTable<DependencyObject, Dictionary<string, string>> Originals = new();
    public static string T(string text) => Language == "en-US" && English.TryGetValue(text, out var value) ? value : text;
    public static string Diagnostic(string text)
    {
        if (Language == "en-US") return T(text);
        return text.Replace("Requires SteamOS 3.10 build 20260924.1000 and exact 7.2.4 kernel", "需要 SteamOS 3.10 build 20260924.1000 和匹配的 7.2.4 内核")
            .Replace("Waydroid r2 requires the accepted SteamOS 3.10 build", "Waydroid r2 需要已适配的 SteamOS 3.10 版本")
            .Replace("Plasma Keyboard dependency is not installed", "系统镜像未安装 Plasma Keyboard 依赖")
            .Replace("Dependency not installed: ", "依赖尚未安装：")
            .Replace("Component resource missing: ", "组件资源缺失（可补齐资源后重试）：")
            .Replace("Component resource manifest is missing: ", "组件资源清单缺失：")
            .Replace("No install payload", "没有可安装的资源")
            .Replace("Invalid Linux Decky binary", "Decky 安装资源无效")
            .Replace("File is not a zip file", "插件归档不是有效的 ZIP 文件")
            .Replace("Incompatible package: ", "软件包版本不兼容：")
            .Replace("Incompatible Gamescope", "Gamescope 版本不兼容")
            .Replace("Existing Flathub remote is required; add it in Discover first", "需要已有 Flathub 源；请先在 Discover 中添加")
            .Replace("Plugin resource is missing or ambiguous", "插件资源缺失或存在多个版本");
    }
    public static void SetLanguage(string language)
    {
        if (language is not ("zh-CN" or "en-US")) throw new ArgumentException("Unsupported installer language.");
        Language = language;
    }
    public static void Apply(DependencyObject root)
    {
        var saved = Originals.GetOrCreateValue(root);
        void Translate(string key, string text, Action<string> write)
        {
            if (!saved.TryGetValue(key, out var original)) saved[key] = original = text;
            write(T(original));
        }
        if (root is Window window) Translate("Title", window.Title, x => window.Title = x);
        if (root is TextBlock block) Translate("Text", block.Text, x => block.Text = x);
        if (root is TextBox box && box.IsReadOnly && English.ContainsKey(box.Text)) Translate("Text", box.Text, x => box.Text = x);
        if (root is HeaderedContentControl header && header.Header is string title) Translate("Header", title, x => header.Header = x);
        if (root is ContentControl control && control.Content is string content) Translate("Content", content, x => control.Content = x);
        foreach (var child in LogicalTreeHelper.GetChildren(root).OfType<DependencyObject>()) Apply(child);
    }
}
