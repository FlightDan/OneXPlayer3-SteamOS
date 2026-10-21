#include "oxp3_gamma22_policy.h"
#include <array>
#include <cassert>
#include <cmath>
#include <iostream>
int main(){
 std::array<uint8_t,128> edid{};
 const uint8_t prefix[]{0,255,255,255,255,255,255,0,0x4c,0x83,1,0x43};
 for(unsigned i=0;i<12;i++)edid[i]=prefix[i];
 auto gate=[&](bool on,bool internal){return KWin::oxp3Gamma22Panel(on,internal,edid);};
 assert(gate(true,true));
 static_assert(KWin::oxp3Gamma22Luminance(true).average == 475);
 static_assert(KWin::oxp3Gamma22Luminance(true).peak == 700);
 static_assert(KWin::oxp3Gamma22Luminance(false).average == 472);
 static_assert(KWin::oxp3Gamma22Luminance(false).peak == 1100);
 assert(!gate(false,true));
 assert(!gate(true,false));
 assert(!KWin::oxp3Gamma22Panel(true,true,std::span(edid).first(16)));
 edid[10]^=1;assert(!gate(true,true));edid[10]^=1;
 edid[8]^=1;assert(!gate(true,true));edid[8]^=1;
 edid[0]=1;assert(!gate(true,true));edid[0]=0;
 std::cout<<"EDID-only internal-panel opt-in and negative gates passed.\n";
 int previous=-1;
 for(double nits:{400.,600.,800.,1100.}){
  int code=std::lround(std::pow(nits/1100.,1./2.2)*255);
  assert(code>previous && code<=255); previous=code;
  std::cout<<nits<<" input nits -> normalized Gamma22 code "<<code<<" (software model only)\n";
 }
}
