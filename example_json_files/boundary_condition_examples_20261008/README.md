# Diverse synthetic boundary condition examples

Git tracks the JSON examples and this README. Local browser preview images remain
ignored and are not required for upload.

Upload the five JSON files in this folder together, or upload them individually.
Each contains one public data object with a distinct descriptive identifier.
The identifiers name the boundary location, loading quantity and material so
the five examples are easy to distinguish in search results and My Data.
Select only the JSON files in the platform's upload picker. Public data is
available to other signed-in platform users and appears in Live Data Objects.
All five identifiers were renamed on 2026-10-27. Uploading these files creates
new objects alongside earlier uploads. Reuploading the same new identifier
uses the ordinary duplicate check.
Existing uploaded objects are not changed by editing these local files.

| File | Current identifier | Previous identifier |
| --- | --- | --- |
| 01_point_tension_aluminium.json | `01-Point-Force-Aluminium` | `d45afab2` |
| 02_edge_compression_steel.json | `02-Edge-Force-Steel` | `22cdfdb0` |
| 03_face_cyclic_shear_titanium.json | `03-Face-Force-Titanium` | `1f84367d` |
| 04_whole_cube_force_displacement_copper.json | `04-Whole-Cube-Force-Copper` | `synthetic-whole-force-copper-20261011` |
| 04_whole_cube_tensor_copper.json | `05-Whole-Cube-Stress-Copper` | `synthetic-whole-stress-copper-one-state-20261011` |

Only the top-level `identifier` values changed in this rename. All other JSON
content and the filenames remain unchanged.

Each file now uses only one boundary target type, including fixed and free
conditions: Point, Edge, Face, or Whole cube. The point file has one loaded point
and four separate fixed points. The edge file has one loaded edge, two separate
fixed edges and one explicitly free edge. The face file has one loaded face and
one fixed face, with X, Y and Z loads on the loaded face. The whole cube files
contain either one stress tensor condition or one scalar force condition.

The existing example JSON was used for field names and structural layout. All
material parameters, dimensions, orientations, boundary conditions and curve
values originated as generated synthetic references. The whole cube display
examples retain selected or complete curves from the original copper reference.
They are explicitly labeled synthetic test data. No finite element solver was run.

| File | Loaded region and direction | Assumed material | Cube side | Load and reference curves |
| --- | --- | --- | --- | --- |
| 01_point_tension_aluminium.json | V111, +X point force | Aluminium reference | 0.8 mm | 32 N endpoint; 41 samples of nominal elastic tension |
| 02_edge_compression_steel.json | V010 to V110, -X/-Y/-Z edge force components; X is parallel to the edge | Steel reference | 1.2 mm | -172.8 N per component; 51 samples of nominal elastic compression along X |
| 03_face_cyclic_shear_titanium.json | Positive Z face, separate X, Y and Z force entries | Titanium reference | 1.5 mm | 405 N amplitude per direction, 0.5 Hz, 4 s; 121 samples of the original cyclic X-on-Z shear reference, not the combined XYZ response |
| 04_whole_cube_tensor_copper.json | All eight vertices identify the whole RVE | Copper reference | 2.0 mm | One explicit symmetric stress tensor at step 1; one corresponding elastic curve sample |
| 04_whole_cube_force_displacement_copper.json | All eight vertices identify the whole cube; X and Z loaded, Y fixed | Copper reference | 2.0 mm | X = 12.5 N and Z = -7.5 N at step 1; 12 retained copper reference samples, not a response to these forces |

## Material and geometry assumptions

For aluminium, steel, titanium and copper, Young's modulus and Poisson ratio
are respectively 70,000 MPa / 0.33, 210,000 MPa / 0.30, 110,000 MPa / 0.34,
and 120,000 MPa / 0.34. These are
illustrative reference assumptions, not calibrated properties of specific alloys.
Temperatures are 293, 310, 350 and 285 K; parameters are held constant and no
thermal response is calculated.
Both whole cube files use the same copper material and geometry metadata.

Structured grids have 10, 12, 15 and 20 cells per side, respectively. Cell sizes
and total counts match the stated cube dimensions. Grain counts are 12, 32, 24
and 8, with the same number of newly generated orientation triples in each case.
Orientations use fixed seeds and angles in radians. They diversify metadata;
the isotropic reference equations do not depend on orientation, and no spatial
grain partition or finite element mesh solution is stored.

## Curve calculations

All three curve groups supply six tensor components and the current MiMeDat
equivalent field. Array order follows the recorded load history; zeros and
negative values are intentional. Every curve in one file has the same length.
Shear strain values are tensor components, half the engineering shear strain.
The complete formulas, parameters and sample history are recorded in
`synthetic_recipe` inside each JSON file.

The point and edge cases use nominal stress `sigma = F/A`, axial strain
`epsilon = sigma/E`, and transverse strain `-nu * sigma/E`. The point case fixes
V000, V010, V001 and V011 individually in X, Y and Z. The edge case fixes
V000 to V100 and V001 to V101 along both edges in X, Y and Z; V011 to V111
is explicitly free. These supports prevent rigid body motion. The regions
between the fixed points or edges are not clamped faces.
These curves are nominal material references; they do not resolve
local point or edge stress concentrations, bending, or support reactions.
The load ramp's sample index is not physical time. For the edge case, magnitude
is the total edge force per loaded component, with an endpoint line load of
-144 N/mm per component. The edge curves describe only the nominal X reference,
not the combined XYZ boundary loading response.

The face case supplies separate 405 N force amplitudes in X, Y and Z for
boundary display. Each magnitude is the total force amplitude on the face,
not a force per vertex or per schematic arrow. Its retained curves describe
only the original X-on-Z shear reference, not the combined XYZ loading.
That reference has area 2.25 mm² and peak shear traction 180 MPa, with the
explicit waveform `tau = 180 * sin(2*pi*0.5*t)` MPa. X traction on a face
whose normal is Z gives the symmetric XZ stress recorded as `stress_13`.

Its simple shear reference has `G = E/(2*(1+nu))`, shear yield stress 120 MPa,
and shear hardening modulus 15,000 MPa. The backstress is `alpha = H*gamma_p`.
If `abs(tau - alpha_old) > 120`, the plastic increment is
`sign(tau - alpha_old)*(abs(tau - alpha_old)-120)/H`. Total
engineering shear is `gamma = tau/G + gamma_p`; the stored tensor strain is
`gamma/2`. This restricted reference produces signed plastic shear, hysteresis
and residual strain. It is not a general multiaxial plasticity implementation or
a solution for the cube's spatial boundary effects.

Total equivalent strain is the instantaneous deviatoric tensor norm. Equivalent
plastic strain accumulates `abs(delta_gamma_p)/sqrt(3)` in the shear case, so it
remains nondecreasing even as signed plastic components reverse. All other
files have zero plastic strain.

The whole RVE tensor case retains one state from an ideal homogeneous periodic
elastic reference. Its strain is calculated from the prescribed stress tensor
using isotropic compliance. The full nine tensor entries include reciprocal
shear components. The sole load entry and curve sample 0 correspond to original
sample index 1 at recorded step 1. No intermediate step or physical time is
inferred. Viewer arrows show component directions, while the numeric matrix
retains actual values.

The whole cube force example demonstrates scalar XYZ boundary display. It
retains all 12 curve samples from the original copper tensor reference, including
unloading and reversals. These curves were not recalculated for its X and Z
forces and Y constraint. The original curve recipe is preserved under
`synthetic_recipe.reference_curve_recipe`. The `/tmp/` archive paths in the
two copper examples record their local source history; they are not portable
dependencies and are not needed for upload.

The standard equation references are [COMSOL's isotropic linear elasticity
documentation](https://doc.comsol.com/6.3/doc/com.comsol.help.sme/sme_ug_theory.06.026.html)
and [Abaqus documentation on kinematic hardening and accumulated plastic
strain](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEMATRefMap/simamat-c-hardening.htm).
Neither solver was used to produce these fixtures.

## Current file checks

On 2026-10-27, all five renamed files passed the platform's required field profile,
including nested and conditional requirements, identifier format, distinct
identifiers across the set and JSON depth checks. All numeric values were finite,
and validation left the JSON bytes unchanged. A byte comparison with the previous
committed files confirmed that only the five top-level identifier values changed.
These checks do not establish a simulated physical response.

## Historical local verification

On 2026-10-13, the five files with their previous identifiers passed the same
required field, identifier and depth checks. The 20 existing required schema and
boundary condition schema tests also passed against an isolated local SQLite
test database on that date.

The earlier four file set passed the platform's required field and conditional
requirement profile before the later Face and whole cube display revisions.
An isolated local SQLite database with DEBUG=True was used for an
actual upload of those four files, detail page data checks, exact JSON export,
CSV row counts, Public access checks and duplicate rejection. Additional checks covered
grid dimensions, orientation counts, finite values, isotropic stress
reconstruction from total minus plastic strain, total-force consistency,
shear yield bounds, plastic accumulation and all whole RVE tensors.

The earlier revision separating boundary target types was checked with a real
upload of four files: the detail table and cube data each contained only the
file's expected target type, including
the automatically displayed free points in the point case. All four objects
appeared in the public activity endpoint for another signed-in user.

Only the point and edge boundary supports, descriptions, support notes and
identifiers changed in that earlier revision. Their applied loads,
material metadata and every curve array were unchanged in that revision.
The Face and whole RVE examples were unchanged in that earlier revision;
they have since changed as described above. These historical checks do not
establish verification of the current five files.

The first 2026-10-10 edge trial kept V010 to V110 and changed its force from -Y to -X,
parallel to that edge. The nominal stress and total strain X/Y components are
swapped to match; all numerical samples, equivalent arrays and plastic strain
were retained. That parallel-only edge identifier was `5bd9f42c`.

The current trial retains the X load and adds independent Y and Z entries on
the same edge, all at -172.8 N with step 1. Each direction now has one schematic
arrow starting at the shared edge midpoint; only the X arrow is parallel to the
edge. The existing nominal X curves are retained and explicitly do not resolve
the combined XYZ loads.
That revision used `22cdfdb0`, generated with the platform's MiMeDat template.
The current identifier is listed above; older uploaded objects are retained.
