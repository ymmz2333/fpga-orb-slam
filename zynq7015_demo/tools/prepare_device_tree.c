/* Build ACZ7015 ORB+HDMI DTB/overlay using unmodified SDK libfdt (BSD option).
 * Preserves PS, memory and peripheral configuration outside named old PL nodes.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <libfdt.h>

static const char *old_pl[]={"Check_GPIO@43c70000","DVP_Capture2DDR@43c00000",
 "Measure_Camera_Parametar@43c60000","audio_formatter@43c10000","i2c@41600000",
 "dma@43000000","clk_wiz@43c20000","i2s_receiver@43c30000","i2s_transmitter@43c40000",
 "v_tc@43c50000","xlnx_vdma_lcd"};
static void need(int rc,const char *name){if(rc<0){fprintf(stderr,"%s: %s\n",name,fdt_strerror(rc));exit(1);}}
static int node(void *f,int parent,const char *name){int n=fdt_subnode_offset(f,parent,name);if(n==-FDT_ERR_NOTFOUND)n=fdt_add_subnode(f,parent,name);need(n,name);return n;}
static void text(void *f,int n,const char *key,const char *value){need(fdt_setprop_string(f,n,key,value),key);}
static void put32(void *f,int n,const char *key,uint32_t v){need(fdt_setprop_u32(f,n,key,v),key);}
static void add_orb(void *f,int parent){
 int n=node(f,parent,"orb60@43c00000");
 fdt32_t reg[]={cpu_to_fdt32(0x43c00000),cpu_to_fdt32(0x10000),cpu_to_fdt32(0x43c10000),cpu_to_fdt32(0x10000),cpu_to_fdt32(0x20000000),cpu_to_fdt32(0x1000000)};
 static const char names[]="layer\0descriptor\0dedicated-ddr";
 text(f,n,"compatible","generic-uio");text(f,n,"status","okay");
 need(fdt_setprop(f,n,"reg",reg,sizeof(reg)),"reg");need(fdt_setprop(f,n,"reg-names",names,sizeof(names)),"reg-names");
}
static void output(void *f,const char *path){
 need(fdt_pack(f),"pack");need(fdt_check_header(f),"header");
 FILE *stream=fopen(path,"wbx");if(!stream){perror(path);exit(1);}
 size_t n=fdt_totalsize(f);if(fwrite(f,1,n,stream)!=n||fclose(stream)){perror("write");exit(1);}
 printf("WROTE %s %lu bytes\n",path,(unsigned long)n);
}
int main(int argc,char **argv){
 if(argc!=4){fprintf(stderr,"Usage: %s original.dtb new.dtb live.dtbo\n",argv[0]);return 2;}
 FILE *stream=fopen(argv[1],"rb");if(!stream){perror(argv[1]);return 1;}
 unsigned char original[65536],tree[65536],overlay[16384];size_t size=fread(original,1,sizeof(original),stream);fclose(stream);
 if(size<40||size>=sizeof(original)){fprintf(stderr,"Unexpected DTB size\n");return 1;}
 need(fdt_check_header(original),"input header");
 if(fdt_totalsize(original)>size||fdt_node_check_compatible(original,0,"xlnx,zynq-7000")){fprintf(stderr,"Wrong board family\n");return 1;}
 int len;const fdt32_t *cells=fdt_getprop(original,0,"#address-cells",&len);
 if(!cells||len!=4||fdt32_to_cpu(*cells)!=1){fprintf(stderr,"Root address cells must be 1\n");return 1;}
 cells=fdt_getprop(original,0,"#size-cells",&len);
 if(!cells||len!=4||fdt32_to_cpu(*cells)!=1){fprintf(stderr,"Root size cells must be 1\n");return 1;}
 int reserved=fdt_path_offset(original,"/reserved-memory/buffer@0x20000000");need(reserved,"reserved DDR");
 const fdt32_t *reg=fdt_getprop(original,reserved,"reg",&len);
 if(!reg||len!=8||fdt32_to_cpu(reg[0])!=0x20000000||fdt32_to_cpu(reg[1])<0x1000000||!fdt_getprop(original,reserved,"no-map",NULL)){
  fprintf(stderr,"Reserved no-map DDR contract failed\n");return 1;
 }
 need(fdt_open_into(original,tree,sizeof(tree)),"expand");
 /* Re-resolve offsets after each edit: libfdt insertions can move nodes. */
 char path[160];size_t i;
 for(i=0;i<sizeof(old_pl)/sizeof(old_pl[0]);i++){
  snprintf(path,sizeof(path),"/amba_pl/%s",old_pl[i]);int n=fdt_path_offset(tree,path);need(n,path);text(tree,n,"status","disabled");
 }
 int old_alias=fdt_path_offset(tree,"/reserved-driver@1");
 if(old_alias>=0)text(tree,old_alias,"status","disabled");
 add_orb(tree,0);
 output(tree,argv[2]);
 need(fdt_create_empty_tree(overlay,sizeof(overlay)),"empty overlay");
 int frag=node(overlay,0,"fragment@0");text(overlay,frag,"target-path","/amba_pl");
 int content=node(overlay,frag,"__overlay__");
 for(i=0;i<sizeof(old_pl)/sizeof(old_pl[0]);i++){
  content=fdt_path_offset(overlay,"/fragment@0/__overlay__");need(content,"overlay body");
  text(overlay,node(overlay,content,old_pl[i]),"status","disabled");
 }
 frag=node(overlay,0,"fragment@1");text(overlay,frag,"target-path","/");content=node(overlay,frag,"__overlay__");
 put32(overlay,content,"#address-cells",1);put32(overlay,content,"#size-cells",1);add_orb(overlay,content);
 if(old_alias>=0){content=fdt_path_offset(overlay,"/fragment@1/__overlay__");text(overlay,node(overlay,content,"reserved-driver@1"),"status","disabled");}
 output(overlay,argv[3]);
 puts("DEVICE_TREE_PREPARED; review and kernel overlay/boot validation required");return 0;
}
