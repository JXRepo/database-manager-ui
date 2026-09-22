# Homepage microstructure

`rve-figure-2.png` is the user's selected Figure_2, copied without changing the
image pixels. It is the second image supplied from a run of
[Kanapy](https://github.com/ICAMS/Kanapy)'s
`examples/RVE_generation/create_rve.py`.

- RVE size: 40 × 40 × 40 µm
- Voxel grid: 30 × 30 × 30, totaling 27,000 voxels
- Periodicity: enabled
- Colors: Kanapy's default `prism` palette, distinguishing grain IDs
- View: elevation 30°, azimuth 30°, upper corner hidden to reveal the interior
- Image: the original 600 × 600 PNG, including its axes, title, and background

The image is displayed directly, preserving the selected figure's colors,
geometry, viewing angle, and shading. The hidden octant is a display cutaway;
the reported size and voxel count describe the complete RVE. The plot axes
show voxel coordinates; the caption gives the physical size in micrometers.
The colors do not encode stress or crystallographic orientation.

Original Figure_2 SHA-256:
`c70403f22b443fba392935f329b5638320a34ae2e7504c3002b6431c5c139ea6`

Exported JSON used to check caption parameters (SHA-256):
`49c550dacdbae23f258c4099d895a9e37dbca27aad30448a20d317ee6333cc35`

Use the original Figure_2 when replacing or moving this asset. Do not recreate
it from the saved voxel array or rerun the example, since the user selected
this specific image. Update the caption alongside the image if the model
parameters change. Source information is maintained here rather than shown
in the homepage caption.

Only the static render is used by the website; Kanapy and plotting packages are
not application dependencies.
