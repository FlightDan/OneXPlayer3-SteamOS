// Bounded HDR10 swapchain presenter. Rectangular clears need no shader compiler.
#define VK_USE_PLATFORM_WAYLAND_KHR
#include <vulkan/vulkan.h>
#include <wayland-client.h>
#include <poll.h>
#include "xdg-shell-client-protocol.h"
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <thread>
#include <vector>
#include <cstring>
#include <string>

static wl_display *display;
static wl_compositor *compositor;
static xdg_wm_base *shell;
static bool configured=false, closed=false;
static int width=1130,height=706;
static void registryGlobal(void*,wl_registry* r,uint32_t name,const char* iface,uint32_t version){
 if(!std::strcmp(iface,"wl_compositor"))compositor=(wl_compositor*)wl_registry_bind(r,name,&wl_compositor_interface,version<4?version:4);
 if(!std::strcmp(iface,"xdg_wm_base"))shell=(xdg_wm_base*)wl_registry_bind(r,name,&xdg_wm_base_interface,1);
}
static void registryRemove(void*,wl_registry*,uint32_t){}
static const wl_registry_listener registryListener={registryGlobal,registryRemove};
static void ping(void*,xdg_wm_base* b,uint32_t serial){xdg_wm_base_pong(b,serial);}
static const xdg_wm_base_listener shellListener={ping};
static void surfaceConfigure(void*,xdg_surface* s,uint32_t serial){xdg_surface_ack_configure(s,serial);configured=true;}
static const xdg_surface_listener surfaceListener={surfaceConfigure};
static void topConfigure(void*,xdg_toplevel*,int32_t w,int32_t h,wl_array*){if(w>0&&h>0){width=w;height=h;}}
static void topClose(void*,xdg_toplevel*){closed=true;}
static void topBounds(void*,xdg_toplevel*,int32_t,int32_t){}
static void topCapabilities(void*,xdg_toplevel*,wl_array*){}
static const xdg_toplevel_listener topListener={topConfigure,topClose,topBounds,topCapabilities};
static void ok(VkResult r,const char* what) { if(r!=VK_SUCCESS) throw std::runtime_error(std::string(what)+" result="+std::to_string(r)); }
static float pq(float nits) {
    const double m1=2610.0/16384, m2=2523.0/32, c1=3424.0/4096, c2=2413.0/128, c3=2392.0/128;
    double x=std::pow(nits/10000.0,m1);
    return std::pow((c1+c2*x)/(1+c3*x),m2);
}
int main(int argc,char**argv) try {
    setvbuf(stdout,nullptr,_IOLBF,0);
    bool four=argc>2 && !std::strcmp(argv[2],"four");
    bool peak=argc>2 && !std::strcmp(argv[2],"peak");
    bool trial=argc>2 && !std::strcmp(argv[2],"trial");
    int seconds=trial ? 10 : (argc>1 ? std::atoi(argv[1]) : 75);
    const float peakNits=1100;
    if(trial) {
        char* end=nullptr;
        long duration=std::strtol(argv[1],&end,10);
        if(!end || *end || duration<1 || duration>10) throw std::runtime_error("HDR trial requires 1..10 seconds; retained trial mode is unavailable");
        seconds=static_cast<int>(duration);
        std::printf("X2MINI_HDR_TRIAL_475_700_V1 DURATION_SECONDS=%d\n",seconds);
    } else if((seconds<1 || seconds>180) && !(seconds==0 && four)) throw std::runtime_error("1..180 seconds or explicit retained four-patch mode required");
    display=wl_display_connect(nullptr);if(!display)throw std::runtime_error("Wayland connection failed");
    auto registry=wl_display_get_registry(display);wl_registry_add_listener(registry,&registryListener,nullptr);wl_display_roundtrip(display);
    if(!compositor||!shell)throw std::runtime_error("KDE compositor/xdg-shell unavailable");
    xdg_wm_base_add_listener(shell,&shellListener,nullptr);
    auto window=wl_compositor_create_surface(compositor);
    auto xsurface=xdg_wm_base_get_xdg_surface(shell,window);xdg_surface_add_listener(xsurface,&surfaceListener,nullptr);
    auto top=xdg_surface_get_toplevel(xsurface);xdg_toplevel_add_listener(top,&topListener,nullptr);
    xdg_toplevel_set_title(top,trial?"X2mini HDR trial: 100 / 300 / 475 / 700 nits (10 seconds maximum)":"KDE mapped HDR: 400 600 800 1100");xdg_toplevel_set_app_id(top,"oxp3-kde-hdr-pattern");
    // The trial must leave KDE's separate confirmation dialog accessible.
    if(!trial) xdg_toplevel_set_fullscreen(top,nullptr);
    wl_surface_commit(window);
    while(!configured){if(wl_display_dispatch(display)<0)throw std::runtime_error("Wayland initial configure failed");}
    std::printf("BACKEND=direct-KDE-Wayland SIZE=%dx%d\n",width,height);
    VkApplicationInfo ai{VK_STRUCTURE_TYPE_APPLICATION_INFO}; ai.pApplicationName="OXP3 bounded HDR pattern"; ai.apiVersion=VK_API_VERSION_1_1;
    const char* ie[]={"VK_KHR_surface","VK_KHR_wayland_surface","VK_EXT_swapchain_colorspace"};
    VkInstanceCreateInfo ic{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ic.pApplicationInfo=&ai; ic.enabledExtensionCount=3; ic.ppEnabledExtensionNames=ie;
    VkInstance inst; ok(vkCreateInstance(&ic,nullptr,&inst),"create instance");
    VkWaylandSurfaceCreateInfoKHR wsi{VK_STRUCTURE_TYPE_WAYLAND_SURFACE_CREATE_INFO_KHR};wsi.display=display;wsi.surface=window;
    VkSurfaceKHR surface;ok(vkCreateWaylandSurfaceKHR(inst,&wsi,nullptr,&surface),"create direct Wayland Vulkan surface");
    uint32_t count=0; ok(vkEnumeratePhysicalDevices(inst,&count,nullptr),"enumerate devices");
    std::vector<VkPhysicalDevice> devices(count); ok(vkEnumeratePhysicalDevices(inst,&count,devices.data()),"devices");
    VkPhysicalDevice physical=VK_NULL_HANDLE; uint32_t family=0;
    for(auto p:devices) {
        uint32_t qc; vkGetPhysicalDeviceQueueFamilyProperties(p,&qc,nullptr);
        std::vector<VkQueueFamilyProperties> qs(qc); vkGetPhysicalDeviceQueueFamilyProperties(p,&qc,qs.data());
        for(uint32_t q=0;q<qc;q++) { VkBool32 present=0; ok(vkGetPhysicalDeviceSurfaceSupportKHR(p,q,surface,&present),"present support");
            if(present && (qs[q].queueFlags&VK_QUEUE_GRAPHICS_BIT)) {physical=p;family=q;break;} }
        if(physical) break;
    }
    if(!physical) throw std::runtime_error("no graphics/present device");
    VkPhysicalDeviceProperties props; vkGetPhysicalDeviceProperties(physical,&props); std::printf("DEVICE=%s\n",props.deviceName);
    uint32_t fc; ok(vkGetPhysicalDeviceSurfaceFormatsKHR(physical,surface,&fc,nullptr),"formats");
    std::vector<VkSurfaceFormatKHR> formats(fc); ok(vkGetPhysicalDeviceSurfaceFormatsKHR(physical,surface,&fc,formats.data()),"formats");
    VkSurfaceFormatKHR selected{}; bool found=false;
    for(auto f:formats) { std::printf("FORMAT=%d COLORSPACE=%d\n",f.format,f.colorSpace);
        if(f.colorSpace==VK_COLOR_SPACE_HDR10_ST2084_EXT && (f.format==VK_FORMAT_A2B10G10R10_UNORM_PACK32 || f.format==VK_FORMAT_A2R10G10B10_UNORM_PACK32)) {selected=f;found=true;} }
    if(!found) throw std::runtime_error("10-bit HDR10 ST2084 surface pair not advertised");
    uint32_t ec; ok(vkEnumerateDeviceExtensionProperties(physical,nullptr,&ec,nullptr),"device extensions");
    std::vector<VkExtensionProperties> exts(ec); ok(vkEnumerateDeviceExtensionProperties(physical,nullptr,&ec,exts.data()),"extensions");
    bool metadata=false; for(auto e:exts) if(!std::strcmp(e.extensionName,"VK_EXT_hdr_metadata")) metadata=true;
    if(trial && !metadata) throw std::runtime_error("HDR trial requires VK_EXT_hdr_metadata");
    std::vector<const char*> de={"VK_KHR_swapchain"}; if(metadata) de.push_back("VK_EXT_hdr_metadata");
    float priority=1; VkDeviceQueueCreateInfo qi{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO}; qi.queueFamilyIndex=family; qi.queueCount=1; qi.pQueuePriorities=&priority;
    VkDeviceCreateInfo di{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO}; di.queueCreateInfoCount=1; di.pQueueCreateInfos=&qi; di.enabledExtensionCount=de.size(); di.ppEnabledExtensionNames=de.data();
    VkDevice dev; ok(vkCreateDevice(physical,&di,nullptr,&dev),"create device"); VkQueue queue; vkGetDeviceQueue(dev,family,0,&queue);
    VkSurfaceCapabilitiesKHR caps; ok(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(physical,surface,&caps),"caps");
    VkExtent2D size=caps.currentExtent; if(size.width==UINT32_MAX) {
        size={(uint32_t)width,(uint32_t)height};
        if(size.width<caps.minImageExtent.width) size.width=caps.minImageExtent.width;
        if(size.width>caps.maxImageExtent.width) size.width=caps.maxImageExtent.width;
        if(size.height<caps.minImageExtent.height) size.height=caps.minImageExtent.height;
        if(size.height>caps.maxImageExtent.height) size.height=caps.maxImageExtent.height;
    }
    if(!(caps.supportedUsageFlags&VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT)) throw std::runtime_error("color attachment unavailable");
    VkSwapchainCreateInfoKHR si{VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR}; si.surface=surface; si.minImageCount=caps.minImageCount+1;
    if(caps.maxImageCount && si.minImageCount>caps.maxImageCount) si.minImageCount=caps.maxImageCount;
    si.imageFormat=selected.format; si.imageColorSpace=selected.colorSpace; si.imageExtent=size; si.imageArrayLayers=1; si.imageUsage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT; si.imageSharingMode=VK_SHARING_MODE_EXCLUSIVE;
    si.preTransform=caps.currentTransform; si.compositeAlpha=VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR; si.presentMode=VK_PRESENT_MODE_FIFO_KHR; si.clipped=VK_TRUE;
    VkSwapchainKHR swap; ok(vkCreateSwapchainKHR(dev,&si,nullptr,&swap),"create swapchain");
    std::printf("SELECTED_FORMAT=%d SELECTED_COLORSPACE=%d SIZE=%ux%u HDR_METADATA=%d\n",selected.format,selected.colorSpace,size.width,size.height,metadata);
    if(peak) std::printf("PATCHES input_nits=400,600,800,1100 total_area_percent=4\n");
    if(trial) std::printf("PATCHES input_nits=100,300,475,700 total_area_percent=4 TRANSFER=ST2084\n");
    if(metadata) {
        auto set=(PFN_vkSetHdrMetadataEXT)vkGetDeviceProcAddr(dev,"vkSetHdrMetadataEXT");
        VkHdrMetadataEXT md{VK_STRUCTURE_TYPE_HDR_METADATA_EXT}; md.displayPrimaryRed={.708f,.292f};md.displayPrimaryGreen={.170f,.797f};md.displayPrimaryBlue={.131f,.046f};md.whitePoint={.3127f,.3290f};
        md.maxLuminance=trial?700:(peak?peakNits:400);md.minLuminance=.0005f;md.maxContentLightLevel=trial?700:(peak?peakNits:400);md.maxFrameAverageLightLevel=trial?475:(peak?60:100);
        if(trial && !set) throw std::runtime_error("HDR metadata entry point unavailable");
        if(set) {set(dev,1,&swap,&md);std::printf("HDR_METADATA_SUBMITTED maxCLL=%.0f maxFALL=%.0f\n",md.maxContentLightLevel,md.maxFrameAverageLightLevel);}
    }
    uint32_t nc; ok(vkGetSwapchainImagesKHR(dev,swap,&nc,nullptr),"images"); std::vector<VkImage> images(nc);ok(vkGetSwapchainImagesKHR(dev,swap,&nc,images.data()),"images");
    VkAttachmentDescription ad{};ad.format=selected.format;ad.samples=VK_SAMPLE_COUNT_1_BIT;ad.loadOp=VK_ATTACHMENT_LOAD_OP_CLEAR;ad.storeOp=VK_ATTACHMENT_STORE_OP_STORE;ad.stencilLoadOp=VK_ATTACHMENT_LOAD_OP_DONT_CARE;ad.stencilStoreOp=VK_ATTACHMENT_STORE_OP_DONT_CARE;ad.initialLayout=VK_IMAGE_LAYOUT_UNDEFINED;ad.finalLayout=VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
    VkAttachmentReference ar{0,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};VkSubpassDescription sub{};sub.pipelineBindPoint=VK_PIPELINE_BIND_POINT_GRAPHICS;sub.colorAttachmentCount=1;sub.pColorAttachments=&ar;
    VkSubpassDependency dep{};dep.srcSubpass=VK_SUBPASS_EXTERNAL;dep.dstSubpass=0;dep.srcStageMask=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;dep.dstStageMask=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;dep.dstAccessMask=VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    VkRenderPassCreateInfo ri{VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO};ri.attachmentCount=1;ri.pAttachments=&ad;ri.subpassCount=1;ri.pSubpasses=&sub;ri.dependencyCount=1;ri.pDependencies=&dep;VkRenderPass render;ok(vkCreateRenderPass(dev,&ri,nullptr,&render),"render pass");
    std::vector<VkImageView> views(nc);std::vector<VkFramebuffer> buffers(nc);
    for(uint32_t i=0;i<nc;i++) {VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};vi.image=images[i];vi.viewType=VK_IMAGE_VIEW_TYPE_2D;vi.format=selected.format;vi.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};ok(vkCreateImageView(dev,&vi,nullptr,&views[i]),"image view");
        VkFramebufferCreateInfo fi{VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO};fi.renderPass=render;fi.attachmentCount=1;fi.pAttachments=&views[i];fi.width=size.width;fi.height=size.height;fi.layers=1;ok(vkCreateFramebuffer(dev,&fi,nullptr,&buffers[i]),"framebuffer");}
    VkCommandPoolCreateInfo pi{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};pi.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;pi.queueFamilyIndex=family;VkCommandPool pool;ok(vkCreateCommandPool(dev,&pi,nullptr,&pool),"pool");
    VkCommandBufferAllocateInfo ci{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ci.commandPool=pool;ci.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ci.commandBufferCount=1;VkCommandBuffer cmd;ok(vkAllocateCommandBuffers(dev,&ci,&cmd),"command buffer");
    VkSemaphoreCreateInfo sem{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};VkSemaphore acquired,done;ok(vkCreateSemaphore(dev,&sem,nullptr,&acquired),"semaphore");ok(vkCreateSemaphore(dev,&sem,nullptr,&done),"semaphore");
    auto start=std::chrono::steady_clock::now();unsigned frames=0;
    while(!closed && std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<seconds) {
        while(wl_display_prepare_read(display)!=0){if(wl_display_dispatch_pending(display)<0)throw std::runtime_error("Wayland pending dispatch failed");} wl_display_flush(display);pollfd fd{wl_display_get_fd(display),POLLIN,0};if(poll(&fd,1,0)>0){if(wl_display_read_events(display)<0)throw std::runtime_error("Wayland read failed");}else{wl_display_cancel_read(display);} wl_display_dispatch_pending(display);
        uint64_t acquireTimeout=UINT64_MAX;
        if(trial) {
            auto remaining=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::seconds(seconds)-(std::chrono::steady_clock::now()-start)).count();
            if(remaining<=0) break;
            acquireTimeout=static_cast<uint64_t>(remaining);
        }
        uint32_t index;ok(vkAcquireNextImageKHR(dev,swap,acquireTimeout,acquired,VK_NULL_HANDLE,&index),"acquire");
        ok(vkResetCommandBuffer(cmd,0),"reset command");VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};ok(vkBeginCommandBuffer(cmd,&begin),"begin");
        VkClearValue black{};black.color.float32[3]=1;VkRenderPassBeginInfo rb{VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};rb.renderPass=render;rb.framebuffer=buffers[index];rb.renderArea.extent=size;rb.clearValueCount=1;rb.pClearValues=&black;vkCmdBeginRenderPass(cmd,&rb,VK_SUBPASS_CONTENTS_INLINE);
        auto rect=[&](float x,float y,float w,float h,float r,float g,float b){VkClearAttachment ca{};ca.aspectMask=VK_IMAGE_ASPECT_COLOR_BIT;ca.clearValue.color={{pq(r),pq(g),pq(b),1}};VkClearRect cr{};cr.rect.offset={(int32_t)(x*size.width),(int32_t)(y*size.height)};cr.rect.extent={(uint32_t)(w*size.width),(uint32_t)(h*size.height)};cr.layerCount=1;vkCmdClearAttachments(cmd,1,&ca,1,&cr);};
        float bright[]={80,100,200,400},dark[]={0,.1f,1,10};
        if(peak || trial) {
            const float peaks[]={trial?100.f:400.f,trial?300.f:600.f,trial?475.f:800.f,trial?700.f:1100.f};
            for(int i=0;i<4;i++) rect(.10f+i*.24f,.40f,.08f,.125f,peaks[i],peaks[i],peaks[i]);
        }
        for(int i=0;!peak && !trial && i<4;i++) {
            float x=.055f+i*.24f;
            rect(x,.18f,.17f,four?.26f:.19f,bright[i],bright[i],bright[i]);
            if(!four) rect(x,.53f,.17f,.19f,dark[i],dark[i],dark[i]);
        }
        // Numeric seven-segment labels, kept outside the sampled patches.
        const unsigned digits[]={0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f};
        auto number=[&](const char* str,float x,float y){for(int c=0;str[c];c++,x+=.025f){if(str[c]=='.'){rect(x,y+.039f,.004f,.005f,150,150,150);continue;}unsigned bits=digits[str[c]-'0'];float a[][4]={{.003f,0,.014f,.004f},{.017f,.004f,.004f,.015f},{.017f,.025f,.004f,.015f},{.003f,.040f,.014f,.004f},{0,.025f,.004f,.015f},{0,.004f,.004f,.015f},{.003f,.020f,.014f,.004f}};for(int k=0;k<7;k++)if(bits&(1<<k))rect(x+a[k][0],y+a[k][1],a[k][2],a[k][3],150,150,150);}};
        const char* bs[]={"80","100","200","400"};const char* ds[]={"0","0.1","1","10"};
        for(int i=0;!peak && !trial && i<4;i++) {number(bs[i],.095f+i*.24f,four?.48f:.40f);if(!four) number(ds[i],.095f+i*.24f,.75f);}
        if(peak) {const char* labels[]={"400","600","800","1100"};for(int i=0;i<4;i++) number(labels[i],.10f+i*.24f,.57f);}
        if(trial) {const char* labels[]={"100","300","475","700"};for(int i=0;i<4;i++) number(labels[i],.10f+i*.24f,.57f);}
        if(!four && !peak && !trial) {rect(.2f,.87f,.15f,.08f,80,0,0);rect(.42f,.87f,.15f,.08f,0,80,0);rect(.64f,.87f,.15f,.08f,0,0,80);}
        rect(.94f,.04f,.025f,.025f,150,150,150);
        if(!trial) number("22",.46f,.07f);
        vkCmdEndRenderPass(cmd);ok(vkEndCommandBuffer(cmd),"end");VkPipelineStageFlags stage=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};submit.waitSemaphoreCount=1;submit.pWaitSemaphores=&acquired;submit.pWaitDstStageMask=&stage;submit.commandBufferCount=1;submit.pCommandBuffers=&cmd;submit.signalSemaphoreCount=1;submit.pSignalSemaphores=&done;ok(vkQueueSubmit(queue,1,&submit,VK_NULL_HANDLE),"submit");
        VkPresentInfoKHR pr{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};pr.waitSemaphoreCount=1;pr.pWaitSemaphores=&done;pr.swapchainCount=1;pr.pSwapchains=&swap;pr.pImageIndices=&index;ok(vkQueuePresentKHR(queue,&pr),"present");
        if(frames==0) std::printf("FIRST_PRESENT_OK\n");
        ok(vkQueueWaitIdle(queue),"queue idle");
        frames++;
        if(frames<=3)std::printf("PRESENTS=%u\n",frames);
        if(frames%300==0) std::printf("PRESENTS=%u\n",frames);
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
    }
    if(trial && frames==0) throw std::runtime_error("HDR trial closed before any successful present");
    std::printf("COMPLETE PRESENTS=%u\n",frames);ok(vkDeviceWaitIdle(dev),"device idle");xdg_toplevel_destroy(top);xdg_surface_destroy(xsurface);wl_surface_destroy(window);wl_display_disconnect(display);
    return 0;
} catch(const std::exception& e) {std::fprintf(stderr,"ERROR: %s\n",e.what());return 1;}
