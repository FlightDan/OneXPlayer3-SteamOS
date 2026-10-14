from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
p = root / 'app/MainWindow.xaml'
s = p.read_text(encoding='utf-8-sig')
old = '<Border Style="{StaticResource Card}"><StackPanel><TextBlock Text="本次安装内容"'
start = s.index(old); end = s.index('</StackPanel></Border>', start) + len('</StackPanel></Border>')
s = s[:start] + '<Border Style="{StaticResource Card}"><StackPanel x:Name="ComponentOptionsHost"/></Border>' + s[end:]
# Language selection is available before choosing the source.
anchor = '<StackPanel x:Name="TargetPage">'
s = s.replace(anchor, anchor + '''
      <DockPanel Margin="0,0,0,16"><TextBlock Text="Language / 语言" VerticalAlignment="Center" Margin="0,0,12,0"/><ComboBox x:Name="InstallerLanguage" Width="170" HorizontalAlignment="Left" SelectionChanged="LanguageChanged"><ComboBoxItem Content="简体中文" Tag="zh-CN"/><ComboBoxItem Content="English" Tag="en-US"/></ComboBox></DockPanel>''')
p.write_text(s, encoding='utf-8')
p = root / 'app/MainWindow.xaml.cs'; s = p.read_text(encoding='utf-8-sig')
s = s.replace('private bool ready;', 'private bool ready;\n    private InstallerOptionsPanel optionsPanel = null!;')
s = s.replace('InitializeComponent(); ready = true;', '''InitializeComponent();
        optionsPanel = new InstallerOptionsPanel(); ComponentOptionsHost.Children.Add(optionsPanel);
        InstallerLanguage.SelectedIndex = InstallerI18n.Language == "en-US" ? 1 : 0;
        InstallerI18n.Apply(this); ready = true;''')
s = s.replace('new(Kind, ImagePath.Text, UsePrepared.IsChecked == true);', 'new(Kind, ImagePath.Text, UsePrepared.IsChecked == true, optionsPanel.Selection);')
s = s.replace('var drive = new DriveInfo', 'ReviewLayout.Text += "\\n\\n" + optionsPanel.Describe();\n        var drive = new DriveInfo')
# Translate Chinese string literals in dynamic window text; invariant protocol literals stay unchanged.
s = re.sub(r'(?<!@)("(?:\\.|[^"\\])*[\u4e00-\u9fff](?:\\.|[^"\\])*")', lambda m: 'InstallerI18n.T(' + m.group(1) + ')', s)
s = s.replace('private void ChoiceChanged', '''private void LanguageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!ready || InstallerLanguage.SelectedItem is not ComboBoxItem item) return;
        InstallerI18n.SetLanguage((string)item.Tag); InstallerI18n.Apply(this); optionsPanel.Refresh(); ShowStep(step);
    }
    private void ChoiceChanged''')
# Translate result component report instead of hiding partial integration.
s = s.replace('private void ShowResult(InstallationSession state)\n    {', '''private void ShowResult(InstallationSession state)
    {''')
s = s.replace('private void UpdateRecovery()', '''private void UpdateRecovery()''')
p.write_text(s, encoding='utf-8')
p = root / 'app/InstallationController.cs'; s = p.read_text(encoding='utf-8-sig')
s = s.replace('InstallationRequest(InstallationTargetKind Kind, string Source, bool Prepared);', 'InstallationRequest(InstallationTargetKind Kind, string Source, bool Prepared, SelectedOptions? Options = null);')
s = s.replace('string Status, string Stage, string? Deployment, string? Error, DateTime UpdatedUtc);', 'string Status, string Stage, string? Deployment, string? Error, DateTime UpdatedUtc, SelectedOptions? Options = null);')
s = s.replace('if (!Enum.IsDefined(request.Kind))', 'if (request.Options != null) InstallerOptions.Validate(request.Options);\n        if (!Enum.IsDefined(request.Kind))', 1)
s = s.replace('null, null, DateTime.UtcNow);', 'null, null, DateTime.UtcNow, request.Options);', 1)
# Options are applied to an independent raw image before holding it for the helper.
s = s.replace('token.ThrowIfCancellationRequested();\n            using var prepared', '''token.ThrowIfCancellationRequested();
            if (request.Options != null)
            {
                Phase("components", InstallerI18n.T("正在配置所选修复、插件与 KDE 语言…"));
                // Never edit a selected prebuilt image in place.
                var selectedImage = Path.Combine(directory, "selected-options.img");
                await Backend.ProcessAsync(Path.Combine(Backend.Root, "runtime/qemu-min/qemu-img.exe"),
                    ["convert", "-O", "raw", image, selectedImage], log, token);
                var resultFile = await Backend.GuestAsync("integration", selectedImage, true, log, token,
                    selection: JsonSerializer.Serialize(request.Options, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower }));
                File.Copy(resultFile, Path.Combine(directory, "components.log"), false);
                image = selectedImage;
            }
            using var prepared''')
p.write_text(s, encoding='utf-8')
# Existing advanced tools remain usable in either language.
p = root / 'app/AdvancedWindow.xaml.cs'; s = p.read_text(encoding='utf-8-sig'); s = s.replace('InitializeComponent();', 'InitializeComponent(); InstallerI18n.Apply(this);',1); p.write_text(s, encoding='utf-8')
p = root / 'app/Backend.cs'; s = p.read_text(encoding='utf-8-sig')
s = s.replace('("smoke" or "inspect"', '("integration" or "smoke" or "inspect"',1)
s = s.replace('(task is "build" or "refine-preview")', '(task is "build" or "refine-preview" or "integration")',1)
anchor = 'CopyDirectory(Path.Combine(Root, "guest"), Path.Combine(payload, "tasks"));'
s = s.replace(anchor, anchor + '''
        if (task == "integration")
        {
            CopyDirectory(Path.Combine(Root, "components"), Path.Combine(payload, "components"));
            CopyDirectory(Path.Combine(Root, "cache/integration"), Path.Combine(payload, "integration"));
            CopyDirectory(Path.Combine(Root, "cache/plugins"), Path.Combine(payload, "plugins"));
            CopyDirectory(Path.Combine(Root, "cache/components/waydroid"), Path.Combine(payload, "waydroid"));
        }''')
p.write_text(s, encoding='utf-8')
