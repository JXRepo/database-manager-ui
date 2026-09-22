# Homepage microstructure

`kanapy-rve-cutaway.png` is a transparent render of the user's synthetic RVE,
generated with [Kanapy](https://github.com/ICAMS/Kanapy) 6.5.4 using
`examples/RVE_generation/create_rve.py` and its `Simulanium_voxels.json` output.

- RVE size: 40 × 40 × 40 µm
- Voxel grid: 30 × 30 × 30, totaling 27,000 voxels
- Periodicity: enabled
- Colors: Kanapy's default `prism` palette, distinguishing grain IDs
- View: elevation 30°, azimuth 30°, upper corner hidden to reveal the interior
- Export: 1448 × 1594 PNG with transparency, without axes or plot title

The image was rendered from the saved voxel array, keeping Kanapy's color
mapping and face shading. The hidden octant is a display cutaway; the reported
size and voxel count describe the complete RVE. The colors do not encode stress
or crystallographic orientation.

Source JSON SHA-256:
`49c550dacdbae23f258c4099d895a9e37dbca27aad30448a20d317ee6333cc35`

To reproduce the model, use the saved voxel JSON from this run. Rerunning the
example generates a new random microstructure. Reshape `Data.Values` using
`Data.Shape` and `Data.Order`, and plot with Kanapy's `plot_voxels_3D` using
`sliced=True` and `silent=True`. Remove the axes and title, then export with a
transparent background and bounds fitted to the model. Update the caption
alongside the image if the model parameters change.

Only the static render is used by the website; Kanapy and plotting packages are
not application dependencies.
