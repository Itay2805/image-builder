# Image Builder
A tool to create images based on a yaml file.

*This tool was made based on https://github.com/no92/vineyard/blob/dev/util/builder*

## Requirements
* dd 
* parted 
* python3
    * pyyaml 

### Optional
* qemu-img (for `vdi`/`vmdk` files)
* mkfs.fat (for `fat12/16/32`)
* mtools (for `fat12/16/32`)
* [echfs-utils](https://github.com/qword-os/echfs) (for `echfs`)

## How to use

You use simply run `image-builder.py <config>` with config being the yaml configuration file.

If the filename ends with `.vmdk` or `.vdi` then the tool will automatically convert the file into these formats.

## YAML Layout

See [example.yaml](example.yaml) for how such a file would look like

* file - the output filename
* size - the total size of the image as `<num>M/G` (`1024M` == `1G`)
* type - the image type (supported: `gpt`, `mbr`)
* partitions - array of partitions
  * `fs` - the file system type (supported: `fat12/16/32`, `echfs`)
  * `size` - the size of the partition (same format as image size), can also define `fit` to take all left space
  * `bootable` - optional, sets the partition as bootable
  * `label` - the partition label
  * `content` - folder whose contents will be copied to the root of the filesystem
