"""Build the pinned Web app with the workbench bridge and local defaults."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SUPER_COMMIT = "4db0e11236bc784d3184a9e252930b4bd53df823"


def localize(source: Path) -> None:
    folder = source / "src/assets/i18n"
    english = json.loads((folder / "en.json").read_text())
    chinese = json.loads((folder / "zh.json").read_text())
    translations = json.loads(Path(__file__).with_name("super-productivity-zh.json").read_text())

    def fill(origin: dict, target: dict, prefix: str = "") -> None:
        for name, value in origin.items():
            key = prefix + name
            if isinstance(value, dict):
                fill(value, target.setdefault(name, {}), key + ".")
            elif key in translations:
                target[name] = translations[key]
            elif not target.get(name):
                raise ValueError(f"简体中文缺少翻译：{key}")

    fill(english, chinese)
    english["PCW"] = {
        "SYSTEM_DEFAULT": "System default", "LOADING_IMAGE": "Loading image…",
        "MARK_DONE": "Mark as done", "MARK_UNDONE": "Mark as undone", "WONT_DO": "Finished as won't do",
    }
    chinese["PCW"] = {
        "SYSTEM_DEFAULT": "系统默认", "LOADING_IMAGE": "正在加载图片…",
        "MARK_DONE": "标记为完成", "MARK_UNDONE": "标记为未完成", "WONT_DO": "已标记为不做",
    }
    localized = json.dumps(chinese, ensure_ascii=False, indent=2)
    localized = re.sub(r"(?<=[\u4e00-\u9fff])收件箱", " 收件箱", localized)
    localized = re.sub(r"收件箱(?=[\u4e00-\u9fff])", "收件箱 ", localized)
    (folder / "zh.json").write_text(localized.replace("收件箱", "Inbox") + "\n")
    (folder / "en.json").write_text(json.dumps(english, ensure_ascii=False, indent=2) + "\n")


def build(source: Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(args, cwd=source, check=True)

    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() != SUPER_COMMIT:
        raise SystemExit("需要 Super Productivity v20.0.0 的独立构建目录")

    def replace(file: str, old: str | tuple[str, ...], new: str) -> None:
        path = source / file
        text = path.read_text()
        if new in text:
            return
        candidates = (old,) if isinstance(old, str) else old
        matches = [candidate for candidate in candidates if candidate in text]
        if len(matches) != 1 or text.count(matches[0]) != 1:
            raise SystemExit(f"上游构建位置已变更：{file}")
        path.write_text(text.replace(matches[0], new))

    localize(source)
    side_nav = source / "src/app/core-ui/magic-side-nav/magic-nav-config.service.ts"
    nav = side_nav.read_text()
    if "id: 'donate'," in nav:
        start = nav.index("      // Donation links are disabled")
        end = nav.index("        : []),\n", start) + len("        : []),\n")
        nav = nav[:start] + nav[end:]
        nav = nav.replace("""  private readonly isDonatePageEnabled = computed(
    () => this._configService.appFeatures().isDonatePageEnabled,
  );
""", "")
        side_nav.write_text(nav)

    effects = "src/app/features/config/store/global-config.effects.ts"
    replace(
        effects,
        ("""        tap((lng) => {
          if (lng === undefined) {
            // Initial state - try autoswitch first, then detect browser language
            const autoswitched = this._languageService.tryAutoswitch();
            if (!autoswitched) this._languageService.setLng();
          } else {
            this._languageService.setLng(lng);
          }
        }),""", "        tap(() => this._languageService.setLng(LanguageCode.zh)),"),
        "        tap((lng) => this._languageService.applyWorkbenchLanguage(lng)),",
    )
    replace("src/index.html", '<html lang="en">', '<html lang="zh-CN">')
    language = "src/app/core/language/language.service.ts"
    replace(language, "  setLng(lng?: LanguageCode | null): void {", """  readonly workbenchLanguage = signal<LanguageCode>(LanguageCode.zh);
  private readonly _workbenchLanguageKey = 'PCW_DAILY_LANGUAGE';

  applyWorkbenchLanguage(previousChoice?: LanguageCode | null): void {
    const choice = localStorage.getItem(this._workbenchLanguageKey) ?? previousChoice;
    this._useWorkbenchLanguage(choice === LanguageCode.en ? LanguageCode.en : LanguageCode.zh);
  }

  toggleWorkbenchLanguage(): void {
    const lng = this.workbenchLanguage() === LanguageCode.en ? LanguageCode.zh : LanguageCode.en;
    localStorage.setItem(this._workbenchLanguageKey, lng);
    this._useWorkbenchLanguage(lng);
  }

  private _useWorkbenchLanguage(lng: LanguageCode): void {
    this.workbenchLanguage.set(lng);
    this.setLng(lng);
  }

  setLng(lng?: LanguageCode | null): void {""")
    replace(language, "    this._translateService.use(lng);",
            "    document.documentElement.lang = lng === LanguageCode.zh ? 'zh-CN' : lng;\n"
            "    this._translateService.use(lng);")
    loader = "src/app/core/http/translate-http-loader-with-fallback.class.ts"
    replace(loader, "import EN_TRANSLATIONS from '../../../assets/i18n/en.json';",
            "import EN_TRANSLATIONS from '../../../assets/i18n/en.json';\n"
            "import ZH_TRANSLATIONS from '../../../assets/i18n/zh.json';")
    replace(loader, "    return EN_TRANSLATIONS as TranslationObject;",
            "    return (lang === 'zh' ? ZH_TRANSLATIONS : EN_TRANSLATIONS) as TranslationObject;")
    replace(loader, "Falling back to bundled English translations", "Falling back to bundled translations")
    replace(loader, 'No bundled translations for "${lang}"; using bundled "${DEFAULT_LANGUAGE}" as fallback.',
            'Using bundled translations for "${lang}".')
    for english_label, chinese_label, key in (
        ("Mark as undone", "标记为未完成", "MARK_UNDONE"),
        ("Finished as won't do", "已标记为不做", "WONT_DO"),
        ("Mark as done", "标记为完成", "MARK_DONE"),
    ):
        replace("src/app/features/tasks/task-summary-table/task-summary-table.component.html",
                (f'aria-label="{english_label}"', f'aria-label="{chinese_label}"'),
                f"""[attr.aria-label]="'PCW.{key}' | translate" """.rstrip())
    attachment = "src/app/features/tasks/task-attachment/task-attachment-list/task-attachment-list.component"
    replace(f"{attachment}.html", ("Loading image...", "正在加载图片…"), "{{ 'PCW.LOADING_IMAGE' | translate }}")
    replace(f"{attachment}.ts", "import { MatIcon } from '@angular/material/icon';",
            "import { MatIcon } from '@angular/material/icon';\nimport { TranslatePipe } from '@ngx-translate/core';")
    replace(f"{attachment}.ts", "    MatIcon,\n", "    MatIcon,\n    TranslatePipe,\n")
    replace("src/app/features/config/default-global-config.const.ts",
            "**How can I best achieve it now?**\n\n**What do I want?**\n\n**Why do I want it?**",
            "**现在可以怎么做？**\n\n**我想达成什么？**\n\n**为什么要做？**")
    form = source / "src/app/features/config/form-cfgs/language-selection-form.const.ts"
    form_text = form.read_text()
    if "      key: 'lng'," in form_text:
        start = form_text.index("    {\n      key: 'lng',")
        end = form_text.index("    {\n      key: 'firstDayOfWeek',", start)
        form_text = form_text[:start] + form_text[end:]
    form.write_text(form_text.replace("{ LanguageCode, DateTimeLocales }", "{ DateTimeLocales }").replace(
        "label: 'System default'", "label: 'PCW.SYSTEM_DEFAULT'",
    ).replace("label: '系统默认'", "label: 'PCW.SYSTEM_DEFAULT'"))

    header = "src/app/core-ui/main-header/main-header.component"
    replace(f"{header}.ts", "import { MatIconButton } from '@angular/material/button';",
            "import { MatButton, MatIconButton } from '@angular/material/button';\n"
            "import { LanguageCode } from '../../core/locale.constants';\n"
            "import { LanguageService } from '../../core/language/language.service';")
    replace(f"{header}.ts", "  imports: [\n    MatIconButton,",
            "  imports: [\n    MatButton,\n    MatIconButton,")
    replace(f"{header}.ts", "  readonly globalConfigService = inject(GlobalConfigService);",
            "  readonly globalConfigService = inject(GlobalConfigService);\n"
            "  readonly languageService = inject(LanguageService);\n"
            "  readonly isEnglish = computed(() => this.languageService.workbenchLanguage() === LanguageCode.en);")
    replace(f"{header}.html", '  <nav\n    class="action-nav-right"', """  @if (isDataLoaded()) {
    <button type="button" class="workbench-language" mat-button
      [attr.lang]="isEnglish() ? 'zh-CN' : 'en'"
      [attr.aria-label]="isEnglish() ? '切换为中文' : 'Switch to English'"
      (click)="languageService.toggleWorkbenchLanguage()">{{ isEnglish() ? '中文' : 'English' }}</button>
  }

  <nav
    class="action-nav-right" """.rstrip())
    replace(f"{header}.scss", ".pill-slot {", """.workbench-language {
  flex: none;
  margin-inline-end: var(--s-half);
  white-space: nowrap;
}

.pill-slot {""")

    bundled = "src/app/plugins/bundled-plugins.const.ts"
    replace(bundled, "  'assets/bundled-plugins/ai-command',", "  'assets/bundled-plugins/ai-command',\n  'assets/bundled-plugins/yubai-workbench',")
    replace(bundled, "  'yesterday-tasks',", "  'yesterday-tasks',\n  'yubai-workbench',")
    replace(
        "src/app/plugins/plugin.service.ts",
        "          // Auto-enable bundled plugins that replace built-in issue providers,",
        "          if (manifest.id === 'yubai-workbench' && !(await this._pluginMetaPersistenceService.hasPluginMetadata(manifest.id))) {\n"
        "            isEnabled = true;\n"
        "            await this._pluginMetaPersistenceService.setPluginEnabled(manifest.id, true);\n"
        "          }\n"
        "          // Auto-enable bundled plugins that replace built-in issue providers,",
    )
    replace(
        "src/app/features/schedule/schedule/schedule.component.ts",
        "    // No saved choice yet: a phone fits under three of the week's seven columns,\n"
        "    // so it starts on one readable day instead.\n"
        "    return this.layoutService.isXs() ? 'day' : 'week';",
        "    // The workbench opens on the full month until the user picks a view.\n    return 'month';",
    )
    defaults = "src/app/features/config/new-install-config.const.ts"
    for feature in ("isSchedulerEnabled", "isFocusModeEnabled"):
        replace(defaults, f"{feature}: false", f"{feature}: true")
    example = source / "src/app/app.component.ts"
    example.write_text(example.read_text().replace(
        "import { ExampleTasksService } from './core/example-tasks/example-tasks.service';\n", "",
    ).replace(
        "  // Injected for side-effect: creates example tasks on first run\n"
        "  private _exampleTasksService = inject(ExampleTasksService);\n", "",
    ))
    path = source / "angular.json"
    config = json.loads(path.read_text())
    web = config["projects"]["sp2"]["architect"]["build"]["configurations"]["productionWeb"]
    # The shell serves immutable files itself. Avoid a stale worker after rollback.
    web["serviceWorker"] = False
    replace(
        "src/main.ts",
        "ServiceWorkerModule.register('sw.js', {\n        enabled:\n"
        "          !IS_ELECTRON &&\n          !IS_NATIVE_PLATFORM &&\n"
        "          (environment.production || environment.stage),",
        "ServiceWorkerModule.register('sw.js', {\n        enabled: false,",
    )
    replace(
        "src/main.ts",
        "    'serviceWorker' in navigator &&\n    (environment.production || environment.stage) &&",
        "    'serviceWorker' in navigator &&\n    false &&",
    )
    path.write_text(json.dumps(config, indent=2) + "\n")
    plugin = source / "src/assets/bundled-plugins/yubai-workbench"
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "manifest.json").write_text(json.dumps({
        "id": "yubai-workbench", "name": "羽白工作台", "version": "1.0.0", "manifestVersion": 1,
        "minSupVersion": "20.0.0", "author": "羽白工作台", "permissions": ["getTasks"],
        "description": "把选中的任务交给本机工作台确认",
    }, ensure_ascii=False))
    assets = Path(__file__).resolve().parents[1] / "app/static"
    shutil.copyfile(assets / "workbench-sp-bridge.js", plugin / "plugin.js")
    shutil.copyfile(assets / "brand/yubai-mark.svg", plugin / "icon.svg")
    run("npm", "run", "prepare")
    run("npm", "run", "plugins:build")
    run("npm", "run", "buildFrontend:prodWeb")
    shutil.copyfile(source / "LICENSE", source / "dist/browser/LICENSE-Super-Productivity.txt")


if __name__ == "__main__":
    build(Path(sys.argv[1]).resolve())
