import { zodResolver } from '@hookform/resolvers/zod';
import { Plus, Trash2 } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import {
  useFieldArray,
  useForm,
  type ArrayPath,
  type Control,
  type FieldErrors,
  type UseFormRegister,
} from 'react-hook-form';
import { profileApi } from '@/api/endpoints';
import { keys, useApiMutation, useProfile } from '@/api/queries';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  PageHeader,
  QueryBoundary,
  SelectField,
  TextArea,
  TextField,
} from '@/components/ui';
import { describeError } from '@/lib/errors';
import { profileSchema, toApiInput, toFormValues, type ProfileFormValues } from './profileForm';

const EMPTY = {
  skill: { name: '', category: 'technical', proficiency: '' } as const,
  education: {
    institution: '',
    degree: '',
    field_of_study: '',
    start_date: '',
    end_date: '',
    description: '',
  },
  work: {
    company: '',
    title: '',
    start_date: '',
    end_date: '',
    is_current: false,
    description: '',
  },
  project: { name: '', description: '', technologies: '', url: '' },
  certification: { name: '', issuer: '', issued_date: '', credential_url: '' },
};

export function ProfilePage() {
  const profile = useProfile();
  return (
    <>
      <PageHeader
        title="Your profile"
        description="Your confirmed profile is the evidence used for job matching and interview questions. Nothing is added to it without your approval."
      />
      <QueryBoundary query={profile} label="Loading your profile">
        {(data) => <ProfileForm initial={toFormValues(data)} email={data.email} />}
      </QueryBoundary>
    </>
  );
}

function ProfileForm({ initial, email }: { initial: ProfileFormValues; email: string }) {
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null);
  const save = useApiMutation(profileApi.update, [keys.profile]);
  const {
    register,
    control,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isDirty },
  } = useForm<ProfileFormValues>({ resolver: zodResolver(profileSchema), defaultValues: initial });

  // Reload the form when the stored profile changes elsewhere (for example a CV was applied).
  useEffect(() => reset(initial), [initial, reset]);

  async function onSubmit(values: ProfileFormValues) {
    setMessage(null);
    try {
      await save.mutateAsync(toApiInput(values));
      setMessage({ tone: 'success', text: 'Profile saved.' });
    } catch (e) {
      setMessage({ tone: 'error', text: describeError(e) });
    }
  }

  const sectionErrors = (name: keyof ProfileFormValues) => {
    const e = errors[name] as { message?: string } | undefined;
    return e?.message ? (
      <p role="alert" className="text-xs text-red-600">
        {e.message}
      </p>
    ) : null;
  };

  return (
    <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-6">
      {message && <Alert tone={message.tone}>{message.text}</Alert>}

      <Card title="Basics">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Email"
            value={email}
            readOnly
            disabled
            hint="Your sign-in address cannot be changed here."
          />
          <TextField
            label="Full name"
            error={errors.full_name?.message}
            {...register('full_name')}
          />
          <TextField
            label="Headline"
            error={errors.headline?.message}
            placeholder="Junior backend developer"
            {...register('headline')}
          />
          <TextField
            label="Preferred roles"
            hint="Separate roles with commas."
            error={errors.preferred_roles?.message}
            {...register('preferred_roles')}
          />
          <SelectField label="Experience level" {...register('experience_level')}>
            <option value="">Not specified</option>
            {['entry', 'junior', 'mid', 'senior', 'lead'].map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </SelectField>
          <SelectField label="Preferred difficulty" {...register('preferred_difficulty')}>
            <option value="">Not specified</option>
            {['beginner', 'intermediate', 'advanced', 'expert'].map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </SelectField>
        </div>
        <div className="mt-4">
          <TextArea
            label="Career objective"
            rows={3}
            error={errors.career_objective?.message}
            {...register('career_objective')}
          />
        </div>
      </Card>

      <ArrayCard
        title="Skills"
        name="skills"
        control={control}
        empty={EMPTY.skill}
        addLabel="Add skill"
        itemLabel="skill"
        error={sectionErrors('skills')}
        render={(index) => (
          <div className="grid gap-3 sm:grid-cols-3">
            <TextField
              label="Skill"
              error={errors.skills?.[index]?.name?.message}
              {...register(`skills.${index}.name`)}
            />
            <SelectField label="Type" {...register(`skills.${index}.category`)}>
              <option value="technical">Technical</option>
              <option value="soft">Soft</option>
            </SelectField>
            <SelectField label="Proficiency" {...register(`skills.${index}.proficiency`)}>
              <option value="">Not specified</option>
              {['beginner', 'intermediate', 'advanced', 'expert'].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </SelectField>
          </div>
        )}
      />

      <ArrayCard
        title="Work experience"
        name="work_experience"
        control={control}
        empty={EMPTY.work}
        addLabel="Add job"
        itemLabel="job"
        error={sectionErrors('work_experience')}
        render={(index) => (
          <WorkFields
            index={index}
            register={register}
            errors={errors}
            current={watch(`work_experience.${index}.is_current`)}
          />
        )}
      />

      <ArrayCard
        title="Education"
        name="education"
        control={control}
        empty={EMPTY.education}
        addLabel="Add education"
        itemLabel="education entry"
        error={sectionErrors('education')}
        render={(index) => (
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField
              label="Institution"
              error={errors.education?.[index]?.institution?.message}
              {...register(`education.${index}.institution`)}
            />
            <TextField
              label="Degree"
              error={errors.education?.[index]?.degree?.message}
              {...register(`education.${index}.degree`)}
            />
            <TextField label="Field of study" {...register(`education.${index}.field_of_study`)} />
            <div className="grid grid-cols-2 gap-3">
              <TextField
                label="Start date"
                placeholder="YYYY-MM-DD"
                error={errors.education?.[index]?.start_date?.message}
                {...register(`education.${index}.start_date`)}
              />
              <TextField
                label="End date"
                placeholder="YYYY-MM-DD"
                error={errors.education?.[index]?.end_date?.message}
                {...register(`education.${index}.end_date`)}
              />
            </div>
          </div>
        )}
      />

      <ArrayCard
        title="Projects"
        name="projects"
        control={control}
        empty={EMPTY.project}
        addLabel="Add project"
        itemLabel="project"
        error={sectionErrors('projects')}
        render={(index) => (
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField
              label="Project name"
              error={errors.projects?.[index]?.name?.message}
              {...register(`projects.${index}.name`)}
            />
            <TextField
              label="Link"
              placeholder="https://"
              error={errors.projects?.[index]?.url?.message}
              {...register(`projects.${index}.url`)}
            />
            <TextField
              label="Technologies"
              hint="Separate with commas."
              {...register(`projects.${index}.technologies`)}
            />
            <TextArea label="Description" rows={2} {...register(`projects.${index}.description`)} />
          </div>
        )}
      />

      <ArrayCard
        title="Certifications"
        name="certifications"
        control={control}
        empty={EMPTY.certification}
        addLabel="Add certification"
        itemLabel="certification"
        error={sectionErrors('certifications')}
        render={(index) => (
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField
              label="Name"
              error={errors.certifications?.[index]?.name?.message}
              {...register(`certifications.${index}.name`)}
            />
            <TextField label="Issuer" {...register(`certifications.${index}.issuer`)} />
            <TextField
              label="Issued"
              placeholder="YYYY-MM-DD"
              error={errors.certifications?.[index]?.issued_date?.message}
              {...register(`certifications.${index}.issued_date`)}
            />
            <TextField
              label="Credential link"
              placeholder="https://"
              error={errors.certifications?.[index]?.credential_url?.message}
              {...register(`certifications.${index}.credential_url`)}
            />
          </div>
        )}
      />

      <div className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-slate-200 bg-slate-50/95 py-3">
        {isDirty && <span className="text-sm text-slate-500">You have unsaved changes.</span>}
        <Button type="submit" loading={save.isPending} disabled={!isDirty}>
          Save profile
        </Button>
      </div>
    </form>
  );
}

function WorkFields({
  index,
  register,
  errors,
  current,
}: {
  index: number;
  register: UseFormRegister<ProfileFormValues>;
  errors: FieldErrors<ProfileFormValues>;
  current: boolean | undefined;
}) {
  const e = errors.work_experience?.[index];
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <TextField
        label="Company"
        error={e?.company?.message}
        {...register(`work_experience.${index}.company`)}
      />
      <TextField
        label="Job title"
        error={e?.title?.message}
        {...register(`work_experience.${index}.title`)}
      />
      <TextField
        label="Start date"
        placeholder="YYYY-MM-DD"
        error={e?.start_date?.message}
        {...register(`work_experience.${index}.start_date`)}
      />
      <TextField
        label="End date"
        placeholder="YYYY-MM-DD"
        disabled={current}
        error={e?.end_date?.message}
        {...register(`work_experience.${index}.end_date`)}
      />
      <Checkbox
        label="I currently work here"
        {...register(`work_experience.${index}.is_current`)}
      />
      <TextArea
        label="What you did"
        rows={2}
        {...register(`work_experience.${index}.description`)}
      />
    </div>
  );
}

function ArrayCard<N extends ArrayPath<ProfileFormValues>>({
  title,
  name,
  control,
  empty,
  addLabel,
  itemLabel,
  error,
  render,
}: {
  title: string;
  name: N;
  control: Control<ProfileFormValues>;
  empty: unknown;
  addLabel: string;
  itemLabel: string;
  error: ReactNode;
  render: (index: number) => ReactNode;
}) {
  const { fields, append, remove } = useFieldArray({ control, name });
  return (
    <Card
      title={title}
      actions={
        <Button variant="secondary" onClick={() => append(empty as never)}>
          <Plus className="size-4" aria-hidden /> {addLabel}
        </Button>
      }
    >
      {fields.length === 0 && <p className="text-sm text-slate-500">Nothing added yet.</p>}
      <ul className="space-y-4">
        {fields.map((field, index) => (
          <li key={field.id} className="rounded-lg border border-slate-200 p-4">
            {render(index)}
            <div className="mt-3 flex justify-end">
              <Button
                variant="ghost"
                onClick={() => remove(index)}
                aria-label={`Remove ${itemLabel} ${index + 1}`}
              >
                <Trash2 className="size-4" aria-hidden /> Remove
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {error}
    </Card>
  );
}
