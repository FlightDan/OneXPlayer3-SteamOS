// SPDX-License-Identifier: GPL-2.0-or-later
#include <QApplication>
#include <QCheckBox>
#include <QLabel>
#include <QVBoxLayout>
#include <QWidget>
#include <QTimer>
#include <QProcess>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QFile>
#include <QSignalBlocker>
#include <QMessageBox>
#include <QLocale>
#include <QUuid>
#include <iostream>
#include "oxp3_gamma22_policy.h"
static QByteArray command(const QString &program,const QStringList &args,int *code=nullptr){
 QProcess p;p.start(program,args);if(!p.waitForFinished(4000)){p.kill();p.waitForFinished();if(code)*code=-1;return {};}
 if(code){*code=p.exitCode();}
 return p.readAllStandardOutput();
}
static QByteArray file(const char *name,bool trim=true){QFile f(QString::fromUtf8(name));if(!f.open(QIODevice::ReadOnly))return {};auto bytes=f.readAll();return trim?bytes.trimmed():bytes;}
static bool mappedReady(){
 auto edid=file("/sys/class/drm/card0-eDP-1/edid",false);
 bool panel=KWin::oxp3Gamma22Panel(true,true,std::span(reinterpret_cast<const uint8_t*>(edid.constData()),edid.size()));
 const auto support=command(QStringLiteral("qdbus6"),{QStringLiteral("org.kde.KWin"),QStringLiteral("/KWin"),QStringLiteral("supportInformation")});
 return panel && (support.contains("OXP3 Gamma22 HDR mapping: enabled (1100/472; EDID-only-v2)")
                 || support.contains("X2MINI_HDR_TRIAL_475_700_V1"))
     && support.contains("OXP3_GAMMA22_POLICY_EDID_ONLY_V2");
}
static bool active(){
 const auto j=QJsonDocument::fromJson(command(QStringLiteral("kscreen-doctor"),{QStringLiteral("-j")})).object();
 for(const auto o:j.value(QStringLiteral("outputs")).toArray()){auto output=o.toObject();if(output.value(QStringLiteral("name")).toString()==QStringLiteral("eDP-1"))return output.value(QStringLiteral("hdr")).toBool()&&output.value(QStringLiteral("wcg")).toBool();}
 return false;
}
static bool setHdr(bool on){
 int status=-1;command(QStringLiteral("kscreen-doctor"),{QStringLiteral("output.eDP-1.hdr.")+(on?QStringLiteral("enable"):QStringLiteral("disable")),QStringLiteral("output.eDP-1.wcg.")+(on?QStringLiteral("enable"):QStringLiteral("disable"))},&status);
 if(!on)command(QStringLiteral("kscreen-doctor"),{QStringLiteral("--dpms"),QStringLiteral("on")});
 return status==0 && active()==on;
}
int main(int argc,char **argv){
 QApplication app(argc,argv);app.setDesktopFileName(QStringLiteral("oxp3-mapped-hdr"));
 if(app.arguments().contains(QStringLiteral("--check"))){bool ready=mappedReady();std::cout<<"mapped_component="<<(ready?"ready":"unavailable")<<" hdr="<<(active()?"on":"off")<<"\n";return ready?0:2;}
 const auto support=command(QStringLiteral("qdbus6"),{QStringLiteral("org.kde.KWin"),QStringLiteral("/KWin"),QStringLiteral("supportInformation")});
 if(support.contains("X2MINI_HDR_TRIAL_475_700_V1")) {
  return QProcess::execute(QStringLiteral("/usr/bin/python3"),{QStringLiteral("-I"),QStringLiteral("-B"),QStringLiteral("/home/deck/.local/lib/oxp3-desktop-hdr-runtime/hdr_trial.py")});
 }
 const bool zh=QLocale::system().language()==QLocale::Chinese;
 QWidget window;window.setWindowTitle(zh?QStringLiteral("桌面映射 HDR"):QStringLiteral("Mapped Desktop HDR"));
 auto layout=new QVBoxLayout(&window);
 auto toggle=new QCheckBox(zh?QStringLiteral("启用映射 HDR（Gamma 2.2）"):QStringLiteral("Enable mapped HDR (Gamma 2.2)"));
 auto details=new QLabel(zh?QStringLiteral("峰值映射 1100 · 全屏映射 472"):QStringLiteral("Peak mapping 1100 · Full-frame mapping 472"));
 auto status=new QLabel;status->setWordWrap(true);
 layout->addWidget(toggle);layout->addWidget(details);layout->addWidget(status);
 bool switching=false;
 auto refresh=[&]{if(switching)return;bool ready=mappedReady();toggle->setEnabled(ready);QSignalBlocker block(toggle);toggle->setChecked(active());status->setText(ready?(zh?QStringLiteral("映射组件已就绪"):QStringLiteral("Mapped HDR is ready")):(zh?QStringLiteral("桌面映射组件尚未启用"):QStringLiteral("Mapped desktop HDR is not active yet")));};
 QObject::connect(toggle,&QCheckBox::clicked,&window,[&](bool on){
  switching=true;toggle->setEnabled(false);
  QString previewUnit;
  if(on){
   previewUnit=QStringLiteral("oxp3-mapped-hdr-preview-")+QUuid::createUuid().toString(QUuid::WithoutBraces).left(8);
   int guardStatus=-1;
   command(QStringLiteral("systemd-run"),{QStringLiteral("--user"),QStringLiteral("--collect"),QStringLiteral("--on-active=15s"),QStringLiteral("--unit=")+previewUnit,QStringLiteral("--setenv=XDG_RUNTIME_DIR=/run/user/1000"),QStringLiteral("--setenv=WAYLAND_DISPLAY=wayland-0"),QStringLiteral("/bin/sh"),QStringLiteral("-c"),QStringLiteral("/usr/bin/kscreen-doctor output.eDP-1.hdr.disable output.eDP-1.wcg.disable; /usr/bin/kscreen-doctor --dpms on")},&guardStatus);
   if(guardStatus!=0){switching=false;refresh();return;}
  }
  if(!mappedReady() || !setHdr(on)){setHdr(false);if(!previewUnit.isEmpty())command(QStringLiteral("systemctl"),{QStringLiteral("--user"),QStringLiteral("stop"),previewUnit+QStringLiteral(".timer"),previewUnit+QStringLiteral(".service")});switching=false;refresh();status->setText(zh?QStringLiteral("切换未完成，已请求恢复普通显示"):QStringLiteral("Switch failed; normal display requested"));return;}
  if(on){
   QMessageBox confirm(QMessageBox::Question,window.windowTitle(),zh?QStringLiteral("画面正常吗？确认后保留；15 秒后自动关闭。"):QStringLiteral("Is the picture normal? Keep to confirm; automatically turns off after 15 seconds."),QMessageBox::Yes|QMessageBox::No,&window);
   confirm.setDefaultButton(QMessageBox::No);QTimer::singleShot(15000,&confirm,&QDialog::reject);
   if(confirm.exec()!=QMessageBox::Yes)setHdr(false);
   command(QStringLiteral("systemctl"),{QStringLiteral("--user"),QStringLiteral("stop"),previewUnit+QStringLiteral(".timer"),previewUnit+QStringLiteral(".service")});
  }
  switching=false;refresh();
 });
 QTimer timer;QObject::connect(&timer,&QTimer::timeout,&window,refresh);timer.start(5000);
 refresh();window.resize(430,150);window.show();return app.exec();
}


