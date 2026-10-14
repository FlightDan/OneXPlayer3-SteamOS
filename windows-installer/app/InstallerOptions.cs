using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

public sealed record SelectedOptions(int Schema, string[] Repairs, string[] Plugins, string InstallerLanguage, string KdeLanguage,
    bool SetDeckPassword = false, bool EnableSsh = false,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] StorageMount[]? StorageMounts = null);
public sealed record OptionItem(string Id, string Zh, string En, bool Default, string[] Dependencies,
    bool Available = true, string? UnavailableZh = null, string? UnavailableEn = null);
public sealed record OptionCatalog(int Schema, string[] Languages, string[] KdeLanguages, OptionItem[] Repairs, OptionItem[] Plugins);

public static class InstallerOptions
{
    public static OptionCatalog Catalog => JsonSerializer.Deserialize<OptionCatalog>(
        File.ReadAllText(Path.Combine(Backend.Root, "components/options.json")),
        new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower, PropertyNameCaseInsensitive = true })
        ?? throw new IOException("Missing installer option catalog.");
    public static bool IsDefault(OptionItem item) => item.Available && (item.Id == "flathub-ustc" ? InstallerI18n.Language == "zh-CN" : item.Default);
    public static string DefaultKdeLanguage => InstallerI18n.Language == "zh-CN" ? "zh_CN" : "en_US";
    public static bool RequiresSystemUpdatePolicy(SelectedOptions options) => options.Repairs.Length > 0 || options.Plugins.Length > 0
        || options.KdeLanguage != "system" || options.SetDeckPassword || options.EnableSsh;
    public static string SystemUpdatePolicyDisclosure => PartitionInventory.L(
        "SteamOS 系统更新暂时暂停，以保留当前设备修复；Steam 客户端和游戏更新照常。恢复系统更新前需检查修复兼容性。",
        "SteamOS system updates will be paused temporarily to preserve the selected device fixes. Steam client and game updates will continue as usual. Check repair compatibility before resuming system updates.");
    public static SelectedOptions Defaults => new(1, Catalog.Repairs.Where(IsDefault).Select(x => x.Id).ToArray(),
        Catalog.Plugins.Where(IsDefault).Select(x => x.Id).ToArray(), InstallerI18n.Language, DefaultKdeLanguage);
    public static void Validate(SelectedOptions value)
    {
        SharedStorage.Validate(value.StorageMounts);
        var catalog = Catalog;
        if (value.Schema != 1 || !catalog.Languages.Contains(value.InstallerLanguage) || !catalog.KdeLanguages.Contains(value.KdeLanguage)
            || value.Repairs == null || value.Plugins == null || value.Repairs.Distinct().Count() != value.Repairs.Length
            || value.Plugins.Distinct().Count() != value.Plugins.Length
            || value.Repairs.Except(catalog.Repairs.Select(x => x.Id)).Any() || value.Plugins.Except(catalog.Plugins.Select(x => x.Id)).Any())
            throw new IOException(InstallerI18n.T("安装选项或语言无效。"));
        var selected = value.Repairs.Concat(value.Plugins).ToHashSet();
        foreach (var item in catalog.Repairs.Concat(catalog.Plugins).Where(x => selected.Contains(x.Id)))
        {
            if (!item.Available) throw new IOException(InstallerI18n.Language == "en-US"
                ? item.UnavailableEn ?? $"{item.En} is not available for installation."
                : item.UnavailableZh ?? $"{item.Zh}暂不可安装。");
            foreach (var dependency in item.Dependencies)
                if (!selected.Contains(dependency)) throw new IOException(InstallerI18n.Language == "en-US"
                    ? $"{item.En} requires {catalog.Repairs.Concat(catalog.Plugins).Single(x => x.Id == dependency).En}. Enable the dependency or disable this item."
                    : $"{item.Zh}需要{catalog.Repairs.Concat(catalog.Plugins).Single(x => x.Id == dependency).Zh}；请开启依赖或关闭该项。");
        }
    }
}

public sealed class InstallerOptionsPanel : StackPanel
{
    private readonly Dictionary<string, CheckBox> boxes = new();
    private readonly ComboBox kde = new() { MinWidth = 210, Margin = new Thickness(0, 6, 0, 14) };
    private readonly CheckBox setDeckPassword = new() { Margin = new Thickness(0, 0, 0, 8) };
    private readonly CheckBox enableSsh = new() { Margin = new Thickness(0, 8, 0, 4) };
    private readonly PasswordBox deckPassword = new() { MaxLength = 128, Margin = new Thickness(0, 2, 0, 8), Padding = new Thickness(8, 5, 8, 5) };
    private readonly PasswordBox deckPasswordConfirm = new() { MaxLength = 128, Margin = new Thickness(0, 2, 0, 8), Padding = new Thickness(8, 5, 8, 5) };
    private readonly TextBlock deckPasswordLabel = new() { TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock deckPasswordConfirmLabel = new() { TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock accessNote = new() { TextWrapping = TextWrapping.Wrap, Foreground = Brushes.SlateGray, Margin = new Thickness(0, 2, 0, 4) };
    private readonly TextBlock systemUpdatePolicyNote = new() { TextWrapping = TextWrapping.Wrap, Foreground = Brushes.SlateGray, Margin = new Thickness(0, 6, 0, 8), LineHeight = 21 };
    private readonly List<(TextBlock Block, string Zh, string En)> labels = new();
    private readonly OptionCatalog catalog = InstallerOptions.Catalog;
    private readonly TextBlock repairHeading = new() { FontSize = 17, FontWeight = FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap };
    private readonly CheckBox allRepairs = new() { IsThreeState = true, Margin = new Thickness(0, 4, 0, 8) };
    private bool updatingRepairs;
    private bool mirrorChanged;
    private bool kdeChanged;
    private bool applyingLanguageDefault;
    internal Expander RepairsExpander { get; } = new() { IsExpanded = false, HorizontalContentAlignment = HorizontalAlignment.Stretch };
    internal IReadOnlyDictionary<string, CheckBox> OptionBoxes => boxes;
    internal ComboBox KdeChoice => kde;
    internal TextBlock SystemUpdatePolicyNote => systemUpdatePolicyNote;
    public event EventHandler? Changed;
    private IEnumerable<OptionItem> DeviceRepairs => catalog.Repairs.Where(x => x.Id is not ("flathub-ustc" or "refind"));
    public InstallerOptionsPanel()
    {
        var repairs = new StackPanel();
        repairs.Children.Add(allRepairs);
        repairs.Children.Add(OptionGrid(DeviceRepairs, selectAll: true));
        RepairsExpander.Header = repairHeading;
        RepairsExpander.Content = repairs;
        Children.Add(RepairsExpander);
        Children.Add(systemUpdatePolicyNote);
        allRepairs.Click += (_, _) =>
        {
            updatingRepairs = true;
            var selected = allRepairs.IsChecked != false;
            foreach (var item in DeviceRepairs.Where(x => x.Available)) boxes[item.Id].IsChecked = selected;
            updatingRepairs = false;
            UpdateRepairSummary();
        };
        Heading("第三方插件预装", "Third-party plugin preinstallation");
        Children.Add(OptionGrid(catalog.Plugins));
        if (catalog.Repairs.Any(x => x.Id == "flathub-ustc"))
        {
            Heading("其他设置", "Other settings");
            Children.Add(OptionGrid(catalog.Repairs.Where(x => x.Id == "flathub-ustc")));
        }
        Heading("账户与远程访问", "Account and remote access");
        labels.Add(((TextBlock)(setDeckPassword.Content = new TextBlock { TextWrapping = TextWrapping.Wrap }),
            "为 deck 用户设置初始密码", "Set an initial password for the deck user"));
        Children.Add(setDeckPassword);
        labels.Add((deckPasswordLabel, "新密码", "New password")); Children.Add(deckPasswordLabel); Children.Add(deckPassword);
        labels.Add((deckPasswordConfirmLabel, "确认密码", "Confirm password")); Children.Add(deckPasswordConfirmLabel); Children.Add(deckPasswordConfirm);
        labels.Add(((TextBlock)(enableSsh.Content = new TextBlock { TextWrapping = TextWrapping.Wrap }),
            "启用 SSH 远程登录", "Enable SSH remote login"));
        Children.Add(enableSsh);
        labels.Add((accessNote,
            "密码仅用于本次安装，不会保存到安装记录或日志。SSH 默认关闭；启用后将在 Steam Deck 下次启动时生效。如需使用密码 SSH 登录，也请勾选设置 deck 密码。",
            "The password is used only for this installation and is not saved in its session record or logs. SSH is off by default and takes effect on the next Steam Deck boot. To sign in over SSH with a password, also select the deck password option."));
        Children.Add(accessNote);
        setDeckPassword.Checked += (_, _) => { UpdateDeckPasswordState(); Changed?.Invoke(this, EventArgs.Empty); };
        setDeckPassword.Unchecked += (_, _) => { UpdateDeckPasswordState(); Changed?.Invoke(this, EventArgs.Empty); };
        enableSsh.Checked += (_, _) => Changed?.Invoke(this, EventArgs.Empty);
        enableSsh.Unchecked += (_, _) => Changed?.Invoke(this, EventArgs.Empty);
        deckPassword.PasswordChanged += (_, _) => { if (!clearingSensitiveInputs) Changed?.Invoke(this, EventArgs.Empty); };
        deckPasswordConfirm.PasswordChanged += (_, _) => { if (!clearingSensitiveInputs) Changed?.Invoke(this, EventArgs.Empty); };
        UpdateDeckPasswordState();
        Heading("SteamOS 桌面语言（KDE）", "SteamOS desktop language (KDE)");
        var languageNote = new TextBlock { TextWrapping = TextWrapping.Wrap, Foreground = Brushes.SlateGray };
        labels.Add((languageNote,
            "默认跟随安装器语言。手动选择后保持你的设置，在安装后登录桌面时生效；Steam 游戏模式的语言请在 Steam 设置中选择。",
            "Defaults to the installer language. A manual choice is kept and takes effect when you log in to the installed desktop. Choose the Steam Gaming Mode language in Steam settings."));
        Children.Add(languageNote);
        var names = new[] { "保持系统默认 / System default", "简体中文", "繁體中文", "English", "日本語", "한국어", "Deutsch", "Français", "Español", "Русский" };
        for (var i = 0; i < catalog.KdeLanguages.Length; i++) kde.Items.Add(new ComboBoxItem { Content = names[i], Tag = catalog.KdeLanguages[i] });
        kde.SelectedItem = kde.Items.Cast<ComboBoxItem>().Single(x => (string)x.Tag == InstallerOptions.DefaultKdeLanguage);
        kde.SelectionChanged += (_, _) =>
        {
            if (applyingLanguageDefault) return;
            kdeChanged = true;
            RefreshSystemUpdatePolicyNote();
            Changed?.Invoke(this, EventArgs.Empty);
        };
        Children.Add(kde);
        Refresh();
    }
    private void Heading(string zh, string en)
    {
        var label = new TextBlock { FontSize = 18, FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 18, 0, 9) };
        labels.Add((label, zh, en)); Children.Add(label);
    }
    private Grid OptionGrid(IEnumerable<OptionItem> items, bool selectAll = false)
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition()); grid.ColumnDefinitions.Add(new ColumnDefinition());
        var index = 0;
        foreach (var item in items)
        {
            if (index % 2 == 0) grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var cell = new StackPanel { Margin = new Thickness(index % 2 == 0 ? 0 : 8, 0, index % 2 == 0 ? 8 : 0, 4) };
            var check = new CheckBox { IsChecked = item.Available && (selectAll || InstallerOptions.IsDefault(item)), IsEnabled = item.Available,
                Margin = new Thickness(0), Tag = item.Id, HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Content = new TextBlock { TextWrapping = TextWrapping.Wrap, LineHeight = 21 } };
            boxes.Add(item.Id, check); cell.Children.Add(check);
            if (selectAll)
            {
                check.Checked += (_, _) => UpdateRepairSummary();
                check.Unchecked += (_, _) => UpdateRepairSummary();
            }
            if (item.Id == "flathub-ustc")
            {
                check.Checked += (_, _) => { if (!applyingLanguageDefault) mirrorChanged = true; };
                check.Unchecked += (_, _) => { if (!applyingLanguageDefault) mirrorChanged = true; };
            }
            if (!item.Available)
            {
                var reason = new TextBlock { TextWrapping = TextWrapping.Wrap, Foreground = Brushes.SlateGray, FontSize = 12,
                    Margin = new Thickness(32, 0, 0, 8) };
                labels.Add((reason, item.UnavailableZh ?? "暂不可安装。", item.UnavailableEn ?? "Not available for installation."));
                cell.Children.Add(reason);
            }
            Grid.SetRow(cell, index / 2); Grid.SetColumn(cell, index % 2); grid.Children.Add(cell); index++;
        }
        return grid;
    }
    private void UpdateRepairSummary()
    {
        if (updatingRepairs) return;
        var available = DeviceRepairs.Where(x => x.Available && boxes.ContainsKey(x.Id)).ToArray();
        var selected = available.Count(x => boxes[x.Id].IsChecked == true);
        allRepairs.IsChecked = selected == available.Length ? true : selected == 0 ? false : null;
        repairHeading.Text = PartitionInventory.L($"设备修复/适配   {selected}/{available.Length} 项", $"Device repairs / support   {selected}/{available.Length}");
    }
    public SelectedOptions Selection => new(1, catalog.Repairs.Where(x => boxes.TryGetValue(x.Id, out var box) && box.IsChecked == true).Select(x => x.Id).ToArray(),
        catalog.Plugins.Where(x => boxes[x.Id].IsChecked == true).Select(x => x.Id).ToArray(), InstallerI18n.Language,
        (string)((ComboBoxItem)kde.SelectedItem).Tag, setDeckPassword.IsChecked == true, enableSsh.IsChecked == true);
    public string? InitialDeckPassword => setDeckPassword.IsChecked == true ? deckPassword.Password : null;
    public void ValidateDeckPassword()
    {
        if (setDeckPassword.IsChecked != true) return;
        var value = deckPassword.Password;
        var bytes = Encoding.UTF8.GetByteCount(value);
        if (string.IsNullOrEmpty(value) || value != deckPasswordConfirm.Password || value.Length < 8 || bytes > 255
            || value.Any(c => c is '\0' or '\r' or '\n'))
            throw new IOException(InstallerI18n.Language == "en-US"
                ? "Enter and confirm a matching deck password of at least 8 characters (maximum 255 UTF-8 bytes)."
                : "请输入并确认一致的 deck 密码；至少 8 个字符，最多 255 个 UTF-8 字节。");
    }
    private bool clearingSensitiveInputs;
    public void ClearSensitiveInputs()
    {
        // The request already holds the validated password. Clearing its UI copy
        // must not invalidate the installation plan the user just approved.
        clearingSensitiveInputs = true;
        try { deckPassword.Clear(); deckPasswordConfirm.Clear(); }
        finally { clearingSensitiveInputs = false; }
    }
    private void UpdateDeckPasswordState()
    {
        var enabled = setDeckPassword.IsChecked == true;
        deckPasswordLabel.IsEnabled = deckPassword.IsEnabled = enabled;
        deckPasswordConfirmLabel.IsEnabled = deckPasswordConfirm.IsEnabled = enabled;
    }
    public void Refresh()
    {
        if (!kdeChanged)
        {
            var previous = kde.SelectedItem;
            applyingLanguageDefault = true;
            try { kde.SelectedItem = kde.Items.Cast<ComboBoxItem>().Single(x => (string)x.Tag == InstallerOptions.DefaultKdeLanguage); }
            finally { applyingLanguageDefault = false; }
            if (previous != kde.SelectedItem) Changed?.Invoke(this, EventArgs.Empty);
        }
        if (!mirrorChanged && boxes.TryGetValue("flathub-ustc", out var mirror))
        {
            applyingLanguageDefault = true;
            mirror.IsChecked = InstallerI18n.Language == "zh-CN";
            applyingLanguageDefault = false;
        }
        allRepairs.Content = PartitionInventory.L("全选设备修复/适配", "Select all device repairs / support");
        UpdateRepairSummary();
        foreach (var item in catalog.Repairs.Concat(catalog.Plugins).Where(x => boxes.ContainsKey(x.Id))) ((TextBlock)boxes[item.Id].Content).Text = InstallerI18n.Language == "en-US" ? item.En : item.Zh;
        foreach (var (block, zh, en) in labels) block.Text = InstallerI18n.Language == "en-US" ? en : zh;
        RefreshSystemUpdatePolicyNote();
    }
    internal void RefreshSystemUpdatePolicyNote()
    {
        systemUpdatePolicyNote.Text = InstallerOptions.SystemUpdatePolicyDisclosure;
        systemUpdatePolicyNote.Visibility = InstallerOptions.RequiresSystemUpdatePolicy(Selection) ? Visibility.Visible : Visibility.Collapsed;
    }
    public string Describe()
    {
        var selected = Selection.Repairs.Concat(Selection.Plugins).ToHashSet();
        return string.Join("\n", catalog.Repairs.Concat(catalog.Plugins).Where(x => selected.Contains(x.Id)).Select(x => InstallerI18n.Language == "en-US" ? x.En : x.Zh))
            + "\nKDE: " + ((ComboBoxItem)kde.SelectedItem).Content
            + "\n" + (InstallerI18n.Language == "en-US" ? "Set deck password: " : "设置 deck 密码：") + (Selection.SetDeckPassword ? (InstallerI18n.Language == "en-US" ? "Yes" : "是") : (InstallerI18n.Language == "en-US" ? "No" : "否"))
            + "\nSSH: " + (Selection.EnableSsh ? (InstallerI18n.Language == "en-US" ? "Enabled" : "启用") : (InstallerI18n.Language == "en-US" ? "Disabled" : "关闭"))
            + (InstallerOptions.RequiresSystemUpdatePolicy(Selection) ? "\n" + InstallerOptions.SystemUpdatePolicyDisclosure : "");
    }
}
