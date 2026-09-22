# Homepage microstructure illustration

`polycrystalline-microstructure.png` is an original AI-assisted illustration
created with the built-in `image_gen` tool. The user's supplied polygonized
microstructure image served as a visual reference for the subject, grain
colors, and translucency.

The image is a conceptual illustration, not a render of the user's simulation
data. Its caption identifies it as a 3D schematic and describes visible grain
geometry. Do not attach numerical RVE dimensions, grain counts, voxel counts,
material names, or boundary conditions to this illustration.

- Asset: 1305 × 1205 PNG with an alpha channel
- Subject: a complete cube of colorful, translucent polyhedral grains
- Presentation: internal grain boundaries, no axes, plotting frame, or text
- Page style: existing pale blue-white background and navy typography
- Generated asset SHA-256: `f36a1eda16ae50326bf99588d3df2ccfa345d00bc8c7623cc7db526bbc43a54e`
- Reference image SHA-256: `c87c9ac729a5f7c3c559e2d036f3a71209920830cf6deed6269ee37d032727a0`

The generator credit is documented here rather than in the homepage caption,
as requested by the user. No plotting or image generation dependencies are
needed to serve this static asset.

## Generation prompt

```text
Use case: scientific-educational, style transfer for a website hero.
Create a bespoke, professional scientific illustration based on the supplied reference: a complete cubic volume of a polycrystalline microstructure composed of irregular polyhedral grains, with semi-transparent outer grains revealing the internal three-dimensional grain structure. The reference establishes the subject and rich multicolor grain palette. Transform its presentation into a refined, publication-quality 3D visualization suitable for a materials simulation data platform.

Scientific form: a dense, continuous, space-filling assembly of interlocking irregular polyhedral grains, with shared polygonal interfaces. Crisp flat outer boundaries form one complete cube. Subtle triangulation and internal facets give depth, like the reference's polygonized structure. Use moderate, controlled translucency so grain boundaries and internal layers remain legible at website size. The cube must read as a material volume, not a collection of separate crystals or loose gemstones. Do not use voxel stairs, repeated grid cubes, atoms, spheres, or decorative lattice structures.

Art direction: precise, elegant, understated scientific visualization. Maintain a full grain palette with amber, ruby red, violet, blue, teal, and leaf green; colors distinguish grains. Improve lighting, separation, fine boundary definition, and material quality over the plotting screenshot. Soft studio illumination from the upper left, restrained highlights and subtle depth shading. Avoid neon glow, glitter, excessive refraction, metallic chrome, and exaggerated glass effects. Camera: balanced orthographic three-quarter view with top and two side faces visible, similar to the reference. No missing corner or cutaway.

Composition: one centered cube, filling about 82 percent of the canvas, with comfortable transparent margins. Generate a genuinely transparent alpha background, not a checkerboard pattern and not an opaque studio backdrop; allow a very soft low-opacity contact shadow only. The image will sit on a pale blue-white page (#f4f7fa / #ffffff), alongside navy typography (#3f4d67). Preserve the colorful specimen; do not recolor it blue-white.

Remove all plotting UI, axes, ticks, grid panes, title, labels, arrows, scale bars, text, signatures, watermarks, and logos. Output only the polished microstructure illustration. This is an illustrative schematic, not a measured dataset or simulated numerical result.
```
