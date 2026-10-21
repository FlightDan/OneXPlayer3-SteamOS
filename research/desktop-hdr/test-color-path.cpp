#include "core/colorspace.h"
#include <QCoreApplication>
#include <QVector3D>
#include <cassert>
#include <cmath>
#include <iostream>
int main(int argc,char **argv){
 QCoreApplication app(argc,argv);
 using namespace KWin;
 ColorDescription input(Colorimetry::BT2020,TransferFunction(TransferFunction::PerceptualQuantizer),203,0.0005,60,1100);
 ColorDescription output(Colorimetry::BT709,TransferFunction(TransferFunction::gamma22,0.0005,1100),203,0.0005,472,1100);
 assert(output.transferFunction().type==TransferFunction::gamma22);
 assert(output.maxHdrLuminance().value()==1100);
 assert(output.maxAverageLuminance().value()==472);
 double previous=-1;
 for(double nits:{80.,100.,200.,400.,600.,800.,1100.}){
  QVector3D signal=input.transferFunction().nitsToEncoded(QVector3D(nits,nits,nits));
  QVector3D encoded=input.mapTo(signal,output,RenderingIntent::AbsoluteColorimetricNoAdaptation);
  assert(std::isfinite(encoded.x()) && encoded.x()>previous && encoded.x()<=1.0001);
  previous=encoded.x();
  std::cout<<nits<<" HDR input -> "<<encoded.x()<<" Gamma22 (compiled KWin color path, no display)\n";
 }
}
