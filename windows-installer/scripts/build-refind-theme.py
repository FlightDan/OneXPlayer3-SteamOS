"""Author deterministic rEFInd UI assets. Does not edit the generated wallpaper."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
import argparse

p=argparse.ArgumentParser(); p.add_argument('--fonts',type=Path,required=True); a=p.parse_args()
root=Path(__file__).resolve().parents[1]/'components/refind'
icons=root/'icons'; theme=root/'theme'; theme.mkdir(exist_ok=True)
S=4
def canvas(n): return Image.new('RGBA',(n*S,n*S))
def drawing(im): return ImageDraw.Draw(im)
def font(n,mono=False): return ImageFont.truetype(str(a.fonts/('DMMono-Regular.ttf' if mono else 'Outfit-Regular.ttf')),n*S)
def box(v): return tuple(round(x*S) for x in v)
def line(d,pts,fill='#7D8792',width=3): d.line([box(pt) for pt in pts],fill=fill,width=width*S,joint='curve')
def ellipse(d,rect,outline='#7D8792',width=3,fill=None): d.ellipse(box(rect),fill=fill,outline=outline,width=width*S)
def label(d,xy,text,size=23): d.text(box(xy),text,font=font(size),fill='#C3CAD3',anchor='mm')
def save(im,path,origin):
    info=PngImagePlugin.PngInfo(); info.add_text('Source',origin)
    im.resize((im.width//S,im.height//S),Image.Resampling.LANCZOS).save(path,pnginfo=info)
for name,text in [('os_linux.png','SteamOS'),('os_win.png','Windows')]:
    im=canvas(256); d=drawing(im)
    d.rounded_rectangle(box((1,1,255,255)),radius=22*S,fill='#12171D',outline='#303A45',width=S)
    if name=='os_linux.png':
        mark=Image.open(root/'steam-silhouette.png').convert('RGBA').resize((112*S,112*S),Image.Resampling.LANCZOS)
        im.alpha_composite(mark,(72*S,43*S))
    else:
        for x in (76,131):
            for y in (47,102): d.rectangle(box((x,y,x+49,y+49)),fill='#7D8792')
    label(d,(128,199),text,25)
    save(im,icons/name,'Graphite Quiet authored UI; Steam silhouette: Simple Icons steam.svg; Windows: four geometric panes')
for name,title,kind in [('func_about.png','Info','info'),('func_shutdown.png','Power','power'),('func_reset.png','Restart','restart'),('func_firmware.png','Firmware','firmware')]:
    im=canvas(96); d=drawing(im)
    if kind=='power':
        d.arc(box((32,18,64,50)),start=-48,end=228,fill='#7D8792',width=3*S)
        line(d,[(48,13),(48,34)])
    elif kind=='info':
        ellipse(d,(32,16,64,48)); line(d,[(48,29),(48,40)]); ellipse(d,(47,23,49,25),fill='#7D8792',width=1)
    elif kind=='restart':
        d.arc(box((32,16,64,48)),start=-55,end=238,fill='#7D8792',width=3*S)
        line(d,[(61,15),(62,27),(51,25)])
    else:
        d.rounded_rectangle(box((35,19,61,45)),radius=4*S,outline='#7D8792',width=3*S)
        for v in (40,48,56):
            line(d,[(v,13),(v,19)],width=2); line(d,[(v,45),(v,51)],width=2)
            line(d,[(29,v-16),(35,v-16)],width=2); line(d,[(61,v-16),(67,v-16)],width=2)
        d.rectangle(box((43,27,53,37)),outline='#7D8792',width=2*S)
    label(d,(48,71),title,14)
    save(im,icons/name,'Graphite Quiet authored functional icon')
for name in ('vol_internal.png','vol_external.png','vol_optical.png','vol_net.png','vol_efi.png'):
    im=canvas(64); d=drawing(im); d.rounded_rectangle(box((14,17,50,47)),radius=5*S,outline='#7D8792',width=3*S)
    line(d,[(20,38),(44,38)],width=2)
    save(im,icons/name,'Graphite Quiet authored volume icon; badges hidden in main menu')
for n,name,radius in [(272,'selection-big.png',30),(112,'selection-small.png',22)]:
    im=canvas(n); d=drawing(im)
    d.rounded_rectangle(box((1.5,1.5,n-1.5,n-1.5)),radius=radius*S,fill='#1B2532',outline='#91ACC9',width=3*S)
    save(im,theme/name,'Graphite Quiet authored selection contour')
im=Image.new('RGBA',(12*96*S,28*S)); d=drawing(im)
for i in range(96):
    # rEFInd complements sprite RGB on a dark backdrop; this displays #C3CAD3.
    d.text(box((i*12+6,14)),chr(i+32) if i<95 else '?',font=font(20,True),fill='#3C352C',anchor='mm')
save(im,theme/'font.png','DM Mono Regular, SIL Open Font License; 96 glyph sprite')
print('Authored 11 icons, 2 selection plates and native font sprite')
